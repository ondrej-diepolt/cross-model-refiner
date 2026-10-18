import json
import logging
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai.lib._pydantic import to_strict_json_schema

from refiner.data import Hodnoceni, Posouzeni, Spotreba, VystupNalezitosti
from refiner.konfigurace import nacti_nastaveni
from refiner.kroky import s_opravou
from refiner.modely.chyby import ChybaModelu
from refiner.modely.codex_cli import CodexModel, druh_chyby_codex, precti_udalosti
from refiner.modely.podproces import VyprselCas, Vysledek
from refiner.porovnani import Pokryti, SeznamPrvku, Srovnani

KOREN = Path(__file__).parent.parent

NALEZITOSTI = {"nalezitosti": [{"id": "N1", "text": "Metodika", "citace": "popis metodiky"}]}
USAGE = {"input_tokens": 2000, "cached_input_tokens": 500, "output_tokens": 300,
         "reasoning_output_tokens": 100}
LOGIN_OK = Vysledek(0, "", "Logged in using ChatGPT\n")


def udalosti(*polozky) -> str:
    return "\n".join(p if isinstance(p, str) else json.dumps(p) for p in polozky) + "\n"


def uspech(usage=USAGE) -> str:
    return udalosti({"type": "thread.started", "thread_id": "t"},
                    {"type": "item.completed", "item": {"type": "agent_message", "text": "hotovo"}},
                    {"type": "turn.completed", "usage": usage})


def ok_vysledek(stdout=None) -> Vysledek:
    return Vysledek(0, uspech() if stdout is None else stdout, "")


def nastaveni():
    return nacti_nastaveni(KOREN / "nastaveni.yaml").modely


class FalesnySpoustec:
    """`login status` vrací LOGIN_OK; jinak bere z fronty dvojici (Vysledek, obsah souboru -o)."""

    def __init__(self, *odpovedi, login=LOGIN_OK):
        self.fronta = list(odpovedi)
        self.login = login
        self.volani = []
        self.login_volani = []

    def __call__(self, argv, stdin, env, cwd, timeout):
        if argv[1:3] == ["login", "status"]:
            self.login_volani.append(SimpleNamespace(argv=argv, env=env, cwd=cwd, timeout=timeout))
            return self.login
        soubory = {}
        vystup = Path(argv[argv.index("-o") + 1])
        for p in vystup.parent.iterdir():
            soubory[p.name] = p.read_text(encoding="utf-8")
        self.volani.append(SimpleNamespace(
            argv=argv, stdin=stdin, env=env, cwd=Path(cwd), timeout=timeout, soubory=soubory,
            prace_obsah=list(Path(cwd).iterdir())))
        odpoved = self.fronta.pop(0)
        if isinstance(odpoved, Exception):
            raise odpoved
        vysledek, obsah = odpoved if isinstance(odpoved, tuple) else (odpoved, None)
        if obsah is not None:
            vystup.write_text(obsah, encoding="utf-8")
        return vysledek


@pytest.fixture(autouse=True)
def _codex_v_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: "C:/fake/codex.exe" if n == "codex" else None)


def model(*odpovedi, **kw):
    spoustec = FalesnySpoustec(*odpovedi, **kw)
    return CodexModel(nastaveni(), spust=spoustec), spoustec


def odp_json(obsah=NALEZITOSTI, stdout=None):
    return (ok_vysledek(stdout), json.dumps(obsah))


def volej_json(m, krok="hodnoceni_1"):
    return m.json("INSTRUKCE", "ZADANI-123", VystupNalezitosti, krok=krok)


def test_argv_izolace_a_stdin():
    m, s = model(odp_json())
    volej_json(m)
    v = s.volani[0]
    argv = v.argv
    for p in ["exec", "--json", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config",
              "--ignore-rules", "-"]:
        assert p in argv
    assert argv[-1] == "-"
    assert argv[argv.index("-s") + 1] == "read-only" and argv[argv.index("-m") + 1] == "gpt-6-astra"
    assert "model_reasoning_effort=high" in argv and "features.shell_tool=false" in argv
    assert argv[argv.index("-C") + 1] == str(v.cwd)
    for c in ["approval_policy=never", "web_search=disabled", "project_doc_max_bytes=0",
              "model_reasoning_summary=none", "skills.include_instructions=false"]:
        assert c in argv
    for f in ["plugins", "apps", "memories", "hooks", "image_generation", "browser_use", "computer_use"]:
        assert argv[argv.index(f) - 1] == "--disable"
    assert "ZADANI-123" in v.stdin and not any("ZADANI-123" in a for a in argv)
    assert not any("INSTRUKCE" in a for a in argv)


def test_instrukce_v_souboru_a_toml_cesta(monkeypatch, tmp_path):
    tomllib = pytest.importorskip("tomllib")
    slozka = tmp_path / "O'Brien Novák"
    slozka.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(slozka))
    m, s = model(odp_json())
    volej_json(m)
    argv = s.volani[0].argv
    hodnota = next(a for a in argv if a.startswith("model_instructions_file="))
    cesta = tomllib.loads(hodnota)["model_instructions_file"]
    assert "O'Brien Novák" in cesta
    assert s.volani[0].soubory["instrukce.md"] == "INSTRUKCE"
    assert Path(cesta).name == "instrukce.md"


def test_schema_je_striktni():
    m, s = model(odp_json())
    volej_json(m)
    argv = s.volani[0].argv
    assert "--output-schema" in argv
    sch = json.loads(s.volani[0].soubory["schema.json"])
    assert sch["additionalProperties"] is False and set(sch["required"]) == set(sch["properties"])
    assert Path(argv[argv.index("--output-schema") + 1]).name == "schema.json"


def test_text_bez_schematu():
    m, s = model((ok_vysledek(), "Ahoj světe"))
    assert m.text("I", "Z", krok="navrh") == "Ahoj světe"
    assert "--output-schema" not in s.volani[0].argv


def test_effort_z_konfigurace_parametr_se_ignoruje():
    m, s = model(odp_json())
    m.json("I", "Z", VystupNalezitosti, krok="k", effort="low")
    assert "model_reasoning_effort=high" in s.volani[0].argv


def test_strict_schema_pro_vsechna_schemata_projektu():
    for c in (VystupNalezitosti, Hodnoceni, Posouzeni, Srovnani, SeznamPrvku, Pokryti):
        to_strict_json_schema(c)


def test_env_bez_klicu(monkeypatch):
    monkeypatch.setenv("CODEX_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-y")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-z")
    monkeypatch.setenv("codex_access_token", "t")
    monkeypatch.setenv("CODEX_HOME", "C:/codex-home")
    m, s = model(odp_json())
    volej_json(m)
    for env in (s.volani[0].env, s.login_volani[0].env):
        assert not {"CODEX_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CODEX_ACCESS_TOKEN"} \
            & {k.upper() for k in env}
        assert env["CODEX_HOME"] == "C:/codex-home"


def test_cwd_prazdny_a_po_volani_smazany():
    m, s = model(odp_json())
    volej_json(m)
    v = s.volani[0]
    assert v.prace_obsah == [] and not v.cwd.exists()
    assert v.timeout == nastaveni().timeout_s


def test_json_uspech_a_spotreba():
    m, _ = model(odp_json())
    assert volej_json(m) == VystupNalezitosti.model_validate(NALEZITOSTI)
    assert m.vyzvedni_spotrebu() == [Spotreba(krok="hodnoceni_1", model="gpt-6-astra", vstup=2000, vystup=300,
                                              cache_cteni=500, predplatne=True)]
    assert m.vyzvedni_spotrebu() == []


def test_ne_json_radky_na_stdout_se_preskoci():
    stdout = udalosti("WARNING: něco se děje", "", {"type": "thread.started"}, "[1, 2]", "{rozbite",
                      {"type": "turn.completed", "usage": USAGE})
    m, _ = model(odp_json(stdout=stdout))
    assert volej_json(m) == VystupNalezitosti.model_validate(NALEZITOSTI)
    assert m.vyzvedni_spotrebu()[0].vstup == 2000


def test_chybejici_vystupni_soubor_je_nevalidni():
    m, _ = model(ok_vysledek())
    with pytest.raises(ChybaModelu) as e:
        volej_json(m)
    assert e.value.druh == "nevalidni_vystup" and e.value.sluzba == "Codex"


def test_prazdny_vystupni_soubor_u_textu_je_jina():
    m, _ = model((ok_vysledek(), "  \n"))
    with pytest.raises(ChybaModelu) as e:
        m.text("I", "Z", krok="navrh")
    assert e.value.druh == "jina"


def test_neplatny_json_vede_na_opravu():
    m, s = model((ok_vysledek(), '{"nalezitosti": "ne seznam"}'), odp_json())
    v = s_opravou(m, "ZADANI", lambda z: m.json("I", z, VystupNalezitosti, krok="k"), lambda _: [], lambda _: "")
    assert v == VystupNalezitosti.model_validate(NALEZITOSTI) and len(s.volani) == 2
    assert "## Oprava" in s.volani[1].stdin


def test_uriznuty_json_je_uriznuto():
    m, _ = model((ok_vysledek(), '{"nalezitosti": [{"id": "N1"'))
    with pytest.raises(ChybaModelu) as e:
        volej_json(m)
    assert e.value.druh == "uriznuto"


@pytest.mark.parametrize("text,druh", [
    ("You’ve hit your usage limit. Visit https://chatgpt.com/settings/usage to purchase more credits",
     "limit_predplatneho"),
    ("usage_limit_reached", "limit_predplatneho"),
    ("quota_exceeded", "limit_predplatneho"),
    ("Not signed in. Please run 'codex login' to sign in with ChatGPT", "neprihlasen"),
    ("The 'gpt-x' model is not supported when using Codex with a ChatGPT account.", "model_nedostupny"),
    ("rate_limit_exceeded", "pretizeni"),
    ("server_overloaded", "pretizeni"),
    ("něco jiného", None),
])
def test_druh_chyby_codex(text, druh):
    assert druh_chyby_codex(text) == druh


def test_turn_failed_mapuje_chybu():
    stdout = udalosti({"type": "thread.started"},
                      {"type": "turn.failed", "error": {"message": "You’ve hit your usage limit. Try later."}})
    m, _ = model(Vysledek(1, stdout, ""))
    with pytest.raises(ChybaModelu) as e:
        volej_json(m)
    assert e.value.druh == "limit_predplatneho" and e.value.sluzba == "Codex"
    assert "usage limit" in e.value.hlaska


def test_model_nedostupny_jmenuje_model():
    stdout = udalosti({"type": "error", "message": "The 'gpt-6-astra' model is not supported when using "
                                                   "Codex with a ChatGPT account."})
    m, _ = model(Vysledek(1, stdout, ""))
    with pytest.raises(ChybaModelu) as e:
        volej_json(m)
    assert e.value.druh == "model_nedostupny" and "gpt-6-astra" in e.value.hlaska


def test_chyba_ve_stderr_pri_nenulovem_kodu():
    m, _ = model(Vysledek(1, "", "Not signed in. Please run 'codex login'"))
    with pytest.raises(ChybaModelu) as e:
        volej_json(m)
    assert e.value.druh == "neprihlasen"


def test_context_window_exceeded_je_jina_s_vysvetlenim():
    stdout = udalosti({"type": "turn.failed", "error": {"message": "context_window_exceeded"}})
    m, _ = model(Vysledek(1, stdout, ""))
    with pytest.raises(ChybaModelu) as e:
        volej_json(m)
    assert e.value.druh == "jina" and "příliš dlouhé" in e.value.hlaska


def test_neznama_chyba_je_jina_bez_klicu():
    m, _ = model(Vysledek(1, "", "boom sk-abc123"))
    with pytest.raises(ChybaModelu) as e:
        volej_json(m)
    assert e.value.druh == "jina" and "sk-abc123" not in e.value.hlaska


def test_chyba_se_spotrebou_zapise_spotrebu():
    stdout = udalosti({"type": "turn.completed", "usage": USAGE},
                      {"type": "turn.failed", "error": {"message": "server_overloaded"}})
    m, _ = model(Vysledek(1, stdout, ""))
    with pytest.raises(ChybaModelu):
        volej_json(m)
    assert len(m.vyzvedni_spotrebu()) == 1


def test_prechodna_chyba_v_proudu_neshodi_uspesny_beh():
    stdout = udalosti({"type": "error", "message": "Reconnecting... 1/5"},
                      {"type": "turn.completed", "usage": USAGE})
    m, _ = model(odp_json(stdout=stdout))
    assert volej_json(m) == VystupNalezitosti.model_validate(NALEZITOSTI)


def test_pouziti_nastroje_jen_varuje(caplog):
    stdout = udalosti({"type": "item.completed", "item": {"type": "command_execution", "command": "ls"}},
                      {"type": "turn.completed", "usage": USAGE})
    m, _ = model(odp_json(stdout=stdout))
    with caplog.at_level(logging.WARNING, logger="refiner.modely.codex_cli"):
        assert volej_json(m) == VystupNalezitosti.model_validate(NALEZITOSTI)
    assert "command_execution" in caplog.text


def test_precti_udalosti():
    stdout = udalosti({"type": "item.started", "item": {"type": "reasoning"}},
                      {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 2}},
                      {"type": "turn.completed", "usage": {"input_tokens": 10, "cached_input_tokens": 4,
                                                           "output_tokens": 20}},
                      {"type": "turn.failed", "error": {"message": "a"}},
                      {"type": "error", "message": "b"})
    usage, zpravy, typy = precti_udalosti(stdout)
    assert usage == {"input_tokens": 11, "cached_input_tokens": 4, "output_tokens": 22}
    assert zpravy == ["a", "b"] and typy == {"reasoning"}
    assert precti_udalosti("nic\n") == (None, [], set())


@pytest.mark.parametrize("login", [
    Vysledek(0, "", "Logged in using an API key - sk-***"),
    Vysledek(1, "", "Not logged in"),
    Vysledek(0, "", ""),
])
def test_login_status_nepripusti_jine_prihlaseni(login):
    with pytest.raises(ChybaModelu) as e:
        model(login=login)
    assert e.value.druh == "neprihlasen" and e.value.sluzba == "Codex"


def test_login_status_api_klic_nesmi_unikout_do_detailu():
    with pytest.raises(ChybaModelu) as e:
        model(login=Vysledek(0, "", "Logged in using an API key - sk-abc123"))
    assert "sk-abc123" not in e.value.detail and "sk-abc123" not in e.value.hlaska


def test_login_status_uspech_na_stdout():
    model(login=Vysledek(0, "Logged in using ChatGPT", ""))


def test_nativni_exe_misto_cmd(monkeypatch, tmp_path):
    exe = (tmp_path / "node_modules/@openai/codex/node_modules/@openai/codex-win32-x64"
           "/vendor/x86_64-pc-windows-msvc/bin/codex.exe")
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    cmd = tmp_path / "codex.cmd"
    cmd.write_text("")
    monkeypatch.setattr("shutil.which", lambda n: str(cmd) if n == "codex" else None)
    m, s = model(odp_json())
    volej_json(m)
    assert s.volani[0].argv[0] == str(exe) and s.login_volani[0].argv[0] == str(exe)


def test_timeout():
    m, _ = model(VyprselCas())
    with pytest.raises(ChybaModelu) as e:
        volej_json(m)
    assert e.value.druh == "timeout" and e.value.sluzba == "Codex"


def test_nenainstalovano(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    with pytest.raises(ChybaModelu) as e:
        CodexModel(nastaveni(), spust=FalesnySpoustec())
    assert e.value.druh == "nenainstalovano" and "příkaz codex nebyl nalezen" in e.value.hlaska


def test_nenainstalovano_pri_spusteni():
    m, _ = model(FileNotFoundError())
    with pytest.raises(ChybaModelu) as e:
        volej_json(m)
    assert e.value.druh == "nenainstalovano"


def test_argv_bez_nastaveni_ktere_codex_nezna():
    """Ostrý test (codex-cli 0.163.0): `tools.view_image` hlásí jako 'unrecognized configuration setting'."""
    m, s = model(odp_json())
    volej_json(m)
    assert not any(a.startswith("tools.") for a in s.volani[0].argv)


def test_varovani_codexu_jako_item_error_neshodi_volani():
    """Skutečný tvar výstupu z ostrého testu: varování o konfiguraci přijde jako item.completed typu error."""
    varovani = {"type": "item.completed", "item": {
        "id": "item_0", "type": "error",
        "message": "Codex is ignoring 1 unrecognized configuration setting. Check for typos or deprecated settings."}}
    stdout = udalosti({"type": "thread.started", "thread_id": "t"}, varovani, varovani, {"type": "turn.started"},
                      {"type": "item.completed", "item": {"id": "item_2", "type": "agent_message", "text": "{}"}},
                      {"type": "turn.completed", "usage": {**USAGE, "cache_write_input_tokens": 0}})
    m, _ = model(odp_json(stdout=stdout))
    assert volej_json(m) == VystupNalezitosti.model_validate(NALEZITOSTI)
    assert m.vyzvedni_spotrebu()[0].vstup == 2000

import json
import logging
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from refiner.data import Spotreba, VystupNalezitosti
from refiner.konfigurace import nacti_nastaveni
from refiner.kroky import s_opravou
from refiner.modely.chyby import ChybaModelu
from refiner.modely.claude_cli import ClaudeCliModel, druh_chyby_claude
from refiner.modely.podproces import VyprselCas, Vysledek

KOREN = Path(__file__).parent.parent

NALEZITOSTI = {"nalezitosti": [{"id": "N1", "text": "Metodika", "citace": "popis metodiky"}]}
USAGE = {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 30,
         "cache_creation_input_tokens": 20}
OK_JSON = {"type": "result", "subtype": "success", "is_error": False, "result": "hotovo",
           "structured_output": NALEZITOSTI, "stop_reason": "end_turn", "usage": USAGE}
AUTH_OK = Vysledek(0, json.dumps({"loggedIn": True, "authMethod": "claude.ai",
                                  "apiProvider": "firstParty"}), "")


def ok(**zmeny) -> Vysledek:
    return Vysledek(0, json.dumps({**OK_JSON, **zmeny}), "")


def nastaveni():
    return nacti_nastaveni(KOREN / "nastaveni.yaml").modely


class FalesnySpoustec:
    """Odpovídá podle argv: `auth status` vrací AUTH_OK, jinak bere další odpověď z fronty."""

    def __init__(self, *odpovedi, auth=AUTH_OK):
        self.fronta = list(odpovedi)
        self.auth = auth
        self.volani = []
        self.auth_volani = []

    def __call__(self, argv, stdin, env, cwd, timeout):
        if argv[1:3] == ["auth", "status"]:
            self.auth_volani.append(SimpleNamespace(argv=argv, env=env, cwd=cwd, timeout=timeout))
            return self.auth
        soubory = {}
        if "--system-prompt-file" in argv:
            slozka = Path(argv[argv.index("--system-prompt-file") + 1]).parent
            soubory = {p.name: p.read_text(encoding="utf-8") for p in slozka.iterdir()}
        self.volani.append(SimpleNamespace(
            argv=argv, stdin=stdin, env=env, cwd=Path(cwd), timeout=timeout, soubory=soubory,
            prace_obsah=list(Path(cwd).iterdir())))
        odpoved = self.fronta.pop(0)
        if isinstance(odpoved, Exception):
            raise odpoved
        return odpoved


@pytest.fixture(autouse=True)
def _claude_v_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: "C:/fake/claude.exe" if n == "claude" else None)


def model(*odpovedi, **kw):
    spoustec = FalesnySpoustec(*odpovedi, **kw)
    return ClaudeCliModel(nastaveni(), spust=spoustec), spoustec


def volej_json(m, **kw):
    return m.json("INSTRUKCE", "ZADANI-123", VystupNalezitosti, krok="nalezitosti", **kw)


def test_zadani_jen_ve_stdin_instrukce_v_souboru():
    m, s = model(ok())
    volej_json(m)
    v = s.volani[0]
    assert "ZADANI-123" in v.stdin and not any("ZADANI-123" in a for a in v.argv)
    assert v.soubory["instrukce.md"] == "INSTRUKCE"
    assert not any("INSTRUKCE" in a for a in v.argv)


def test_prepinace_izolace():
    m, s = model(ok())
    volej_json(m)
    argv = s.volani[0].argv
    for p in ["-p", "--output-format", "json", "--no-session-persistence", "--safe-mode",
              "--strict-mcp-config", "--permission-prompts"]:
        assert p in argv
    assert argv[argv.index("--tools") + 1] == "" and "--bare" not in argv
    assert argv[argv.index("--disallowedTools") + 1] == "mcp__*"
    assert argv[argv.index("--model") + 1] == "claude-opus-5-5"
    schema = json.loads(argv[argv.index("--json-schema") + 1])
    assert schema == VystupNalezitosti.model_json_schema()


def test_model_a_effort_z_konfigurace_a_extrakce():
    m, s = model(ok(), ok(), ok(result="text"))
    volej_json(m)
    volej_json(m, effort="low")
    m.text("I", "Z", krok="navrh")
    efforty = [v.argv[v.argv.index("--effort") + 1] for v in s.volani]
    assert efforty == ["high", "low", "high"]
    assert "--json-schema" not in s.volani[2].argv


def test_env_bez_klicu(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-y")
    monkeypatch.setenv("CLAUDE_CODE_SIMPLE", "1")
    monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", "low")
    monkeypatch.setenv("Anthropic_Auth_Token", "t")
    m, s = model(ok())
    volej_json(m)
    for env in (s.volani[0].env, s.auth_volani[0].env):
        assert not {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CLAUDE_CODE_SIMPLE", "CLAUDE_CODE_EFFORT_LEVEL",
                    "ANTHROPIC_AUTH_TOKEN"} & {k.upper() for k in env}
        assert env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
        assert env["CLAUDE_CODE_DISABLE_ATTACHMENTS"] == "1"
        assert env["CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS"] == "1"


def test_cwd_prazdny_a_po_volani_smazany():
    m, s = model(ok())
    volej_json(m)
    v = s.volani[0]
    assert v.prace_obsah == [] and not v.cwd.exists()
    assert s.volani[0].timeout == nastaveni().timeout_s


def test_json_uspech_a_spotreba():
    m, _ = model(ok())
    assert volej_json(m) == VystupNalezitosti.model_validate(NALEZITOSTI)
    assert m.vyzvedni_spotrebu() == [Spotreba(krok="nalezitosti", model="claude-opus-5-5", vstup=100,
                                              vystup=50, cache_cteni=30, cache_zapis=20, predplatne=True)]
    assert m.vyzvedni_spotrebu() == []


def test_text_vraci_result():
    m, _ = model(ok(result="Ahoj světe"))
    assert m.text("I", "Z", krok="navrh") == "Ahoj světe"


def test_json_bez_structured_output_je_nevalidni():
    odp = {k: v for k, v in OK_JSON.items() if k != "structured_output"}
    m, _ = model(Vysledek(0, json.dumps(odp), ""))
    with pytest.raises(ChybaModelu) as e:
        volej_json(m)
    assert e.value.druh == "nevalidni_vystup" and e.value.sluzba == "Claude Code"


def test_json_vycerpane_pokusy_schematu_je_nevalidni():
    odp = {"type": "result", "subtype": "error_max_structured_output_retries", "is_error": True,
           "errors": ["x"], "usage": USAGE}
    m, _ = model(Vysledek(1, json.dumps(odp), ""))
    with pytest.raises(ChybaModelu) as e:
        volej_json(m)
    assert e.value.druh == "nevalidni_vystup"
    assert len(m.vyzvedni_spotrebu()) == 1   # tokeny se platí i při chybě


def test_json_neplatny_vuci_schematu_vede_na_opravu():
    spatne = ok(structured_output={"nalezitosti": "ne seznam"})
    m, s = model(spatne, ok())
    v = s_opravou(m, "ZADANI", lambda z: m.json("I", z, VystupNalezitosti, krok="nalezitosti"),
                  lambda _: [], lambda _: "")
    assert v == VystupNalezitosti.model_validate(NALEZITOSTI) and len(s.volani) == 2
    assert "## Oprava" in s.volani[1].stdin


def test_uriznuto_a_odmitnuti():
    m, _ = model(ok(stop_reason="max_tokens"), ok(stop_reason="refusal"))
    with pytest.raises(ChybaModelu) as e:
        volej_json(m)
    assert e.value.druh == "uriznuto" and "uříznutá" in e.value.hlaska
    with pytest.raises(ChybaModelu) as e:
        volej_json(m)
    assert e.value.druh == "odmitnuti"


@pytest.mark.parametrize("text,druh", [
    ("Not logged in · Please run /login", "neprihlasen"),
    ("Login expired · Please run /login", "neprihlasen"),
    ("Failed to authenticate. API Error: 401 OAuth token has expired", "neprihlasen"),
    ("You've hit your session limit · resets 3:45pm", "limit_predplatneho"),
    ("You've hit your weekly limit · resets Mon 12:00am", "limit_predplatneho"),
    ("Request rejected (429)", "pretizeni"),
    ("Server is temporarily limiting requests", "pretizeni"),
    ("Claude Opus is not available with the Claude Pro plan", "model_nedostupny"),
    ("Model claude-x is not a recognized model id", "model_nedostupny"),
    ("něco úplně jiného", None),
])
def test_druh_chyby_claude(text, druh):
    assert druh_chyby_claude(text) == druh


@pytest.mark.parametrize("text,druh", [
    ("Not logged in · Please run /login", "neprihlasen"),
    ("You've hit your session limit · resets 3:45pm", "limit_predplatneho"),
    ("Claude Opus is not available with the Claude Pro plan", "model_nedostupny"),
    ("Request rejected (429)", "pretizeni"),
])
def test_holy_text_s_nenulovym_kodem(text, druh):
    m, _ = model(Vysledek(1, text, ""))
    with pytest.raises(ChybaModelu) as e:
        volej_json(m)
    assert e.value.druh == druh and e.value.sluzba == "Claude Code"


def test_limit_a_model_nesou_detail():
    m, _ = model(Vysledek(1, "You've hit your session limit · resets 3:45pm", ""),
                 Vysledek(1, "Claude Opus is not available with the Claude Pro plan", ""))
    with pytest.raises(ChybaModelu) as e:
        volej_json(m)
    assert "resets 3:45pm" in e.value.hlaska
    with pytest.raises(ChybaModelu) as e:
        volej_json(m)
    assert "claude-opus-5-5" in e.value.hlaska


def test_chyba_v_json_obalce_se_mapuje():
    odp = {"type": "result", "subtype": "success", "is_error": True, "usage": USAGE,
           "result": "You've hit your weekly limit · resets Mon 12:00am"}
    m, _ = model(Vysledek(1, json.dumps(odp), ""))
    with pytest.raises(ChybaModelu) as e:
        volej_json(m)
    assert e.value.druh == "limit_predplatneho"


def test_chyba_site_je_sit():
    odp = {"type": "result", "subtype": "error_during_execution", "is_error": True, "usage": USAGE,
           "result": "API Error: connect ECONNRESET"}
    m, _ = model(Vysledek(1, json.dumps(odp), ""))
    with pytest.raises(ChybaModelu) as e:
        volej_json(m)
    assert e.value.druh == "sit"


def test_neznama_chyba_je_jina_bez_klicu():
    m, _ = model(Vysledek(1, "boom sk-abc123", "stderr sk-def456"))
    with pytest.raises(ChybaModelu) as e:
        volej_json(m)
    assert e.value.druh == "jina" and "sk-abc123" not in e.value.hlaska and "sk-def456" not in e.value.hlaska


def test_nejson_s_kodem_nula_je_jina():
    m, _ = model(Vysledek(0, "to není json", ""))
    with pytest.raises(ChybaModelu) as e:
        volej_json(m)
    assert e.value.druh == "jina"


def test_timeout():
    m, _ = model(VyprselCas())
    with pytest.raises(ChybaModelu) as e:
        volej_json(m)
    assert e.value.druh == "timeout" and e.value.sluzba == "Claude Code"


def test_nenainstalovano_v_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    with pytest.raises(ChybaModelu) as e:
        ClaudeCliModel(nastaveni(), spust=FalesnySpoustec())
    assert e.value.druh == "nenainstalovano" and "příkaz claude nebyl nalezen" in e.value.hlaska


def test_nenainstalovano_pri_spusteni():
    m, _ = model(FileNotFoundError())
    with pytest.raises(ChybaModelu) as e:
        volej_json(m)
    assert e.value.druh == "nenainstalovano"


def test_prikaz_z_nastaveni(tmp_path):
    program = tmp_path / "muj-claude.exe"
    program.write_text("")
    n = nastaveni()
    n = n.model_copy(update={"predplatne": n.predplatne.model_copy(
        update={"claude": n.predplatne.claude.model_copy(update={"prikaz": str(program)})})})
    s = FalesnySpoustec(ok())
    ClaudeCliModel(n, spust=s).json("I", "Z", VystupNalezitosti, krok="k")
    assert s.volani[0].argv[0] == str(program) and s.auth_volani[0].argv[0] == str(program)


def test_prihlaseni_api_klicem_odmitne():
    auth = Vysledek(0, json.dumps({"loggedIn": True, "authMethod": "api_key"}), "")
    with pytest.raises(ChybaModelu) as e:
        model(auth=auth)
    assert e.value.druh == "neprihlasen" and "api_key" in e.value.detail


@pytest.mark.parametrize("auth", [
    Vysledek(0, json.dumps({"loggedIn": False}), ""),
    Vysledek(1, "Not logged in", ""),
    Vysledek(0, "[]", ""),
])
def test_nepřihlášený_nebo_necitelny_stav(auth):
    with pytest.raises(ChybaModelu) as e:
        model(auth=auth)
    assert e.value.druh == "neprihlasen"


def test_kontrola_prihlaseni_bezi_v_prazdnem_adresari_s_limitem():
    m, s = model()
    a = s.auth_volani[0]
    assert a.timeout == 60 and a.argv[1:] == ["auth", "status"]


def test_cesta_s_mezerou_a_apostrofem(monkeypatch, tmp_path):
    slozka = tmp_path / "O'Brien Novák"
    slozka.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(slozka))
    m, s = model(ok())
    volej_json(m)
    v = s.volani[0]
    assert v.soubory["instrukce.md"] == "INSTRUKCE"
    assert "O'Brien Novák" in v.argv[v.argv.index("--system-prompt-file") + 1]


def test_debug_log_neobsahuje_instrukce(caplog):
    m, _ = model(ok())
    with caplog.at_level(logging.DEBUG, logger="refiner.modely.claude_cli"):
        volej_json(m)
    assert "INSTRUKCE" not in caplog.text and "ZADANI-123" not in caplog.text

import sys
import time
from pathlib import Path

import pytest

from refiner.modely import podproces
from refiner.modely.podproces import (
    ODSTRANIT,
    VyprselCas,
    ciste_prostredi,
    docasne_adresare,
    najdi_program,
    nativni_codex,
    spust_proces,
)

NATIVNI = Path("node_modules/@openai/codex/node_modules/@openai/codex-win32-x64"
               "/vendor/x86_64-pc-windows-msvc/bin/codex.exe")


def _skript(tmp_path, kod):
    cesta = tmp_path / "skript.py"
    cesta.write_text(kod, encoding="utf-8")
    return cesta


def test_ciste_prostredi_odstrani_klice():
    env = ciste_prostredi({"ANTHROPIC_API_KEY": "sk-a", "anthropic_api_key": "sk-b", "OPENAI_API_KEY": "x",
                           "CODEX_API_KEY": "x", "CLAUDE_CODE_OAUTH_TOKEN": "x", "CLAUDE_CODE_SIMPLE": "1",
                           "CLAUDECODE": "1", "CLAUDE_CONFIG_DIR": "C:/c", "CODEX_HOME": "C:/x", "PATH": "p"},
                          navic={"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"})
    assert env == {"CLAUDE_CONFIG_DIR": "C:/c", "CODEX_HOME": "C:/x", "PATH": "p",
                   "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"}


def test_ciste_prostredi_bere_os_environ_a_odstrani_i_jine_anthropic_openai(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-a")
    monkeypatch.setenv("openai_api_key", "sk-b")
    monkeypatch.setenv("ANTHROPIC_CUSTOM_HEADERS", "x")
    monkeypatch.setenv("OPENAI_ORG_ID", "x")
    env = ciste_prostredi()
    assert not [k for k in env if k.upper().startswith(("ANTHROPIC_", "OPENAI_"))]


def test_navic_nesmi_vratit_klic():
    with pytest.raises(ValueError):
        ciste_prostredi({}, navic={"anthropic_api_key": "sk-x"})


def test_odstranit_obsahuje_vsechny_z_designu():
    assert {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY",
            "CODEX_ACCESS_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "ANTHROPIC_BASE_URL", "OPENAI_BASE_URL",
            "CLAUDE_CODE_EFFORT_LEVEL", "ANTHROPIC_MODEL", "OPENAI_IDENTITY_TOKEN_FILE"} <= set(ODSTRANIT)


def test_stdin_utf8_s_diakritikou_a_dlouhy(tmp_path):
    skript = _skript(tmp_path, "import sys\n"
                               "data = sys.stdin.buffer.read()\n"
                               "sys.stdout.buffer.write(data)\n")
    text = "Příliš žluťoučký kůň úpěl ďábelské ódy. " * 5000   # ~200 000 znaků
    v = spust_proces([sys.executable, str(skript)], text, ciste_prostredi(), tmp_path, 30)
    assert v.kod == 0 and v.stdout == text


def test_env_a_cwd_se_predaji(tmp_path):
    skript = _skript(tmp_path, "import os, sys\n"
                               "sys.stdout.write(os.getcwd() + '|' + os.environ.get('X', ''))\n")
    prace = tmp_path / "prace"
    prace.mkdir()
    env = ciste_prostredi(navic={"X": "hodnota"})
    v = spust_proces([sys.executable, str(skript)], "", env, prace, 30)
    assert v.kod == 0 and v.stdout == f"{prace.resolve()}|hodnota"


def test_nenulovy_kod_a_stderr(tmp_path):
    skript = _skript(tmp_path, "import sys\nsys.stderr.write('chyba')\nsys.exit(3)\n")
    v = spust_proces([sys.executable, str(skript)], "", ciste_prostredi(), tmp_path, 30)
    assert (v.kod, v.stderr) == (3, "chyba")


def test_chybejici_program_vyhodi_filenotfound(tmp_path):
    with pytest.raises(FileNotFoundError):
        spust_proces([str(tmp_path / "neexistuje.exe")], "", ciste_prostredi(), tmp_path, 5)


def test_timeout_zabije_i_podrizene_procesy(tmp_path):
    skript = _skript(tmp_path, "import subprocess, sys, time\n"
                               "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                               "time.sleep(60)\n")
    start = time.monotonic()
    with pytest.raises(VyprselCas):
        spust_proces([sys.executable, str(skript)], "", ciste_prostredi(), tmp_path, 1)
    assert time.monotonic() - start < 15


def test_najdi_program_nastavena_cesta_ma_prednost(tmp_path, monkeypatch):
    program = tmp_path / "muj-claude.exe"
    program.write_text("")
    monkeypatch.setattr("shutil.which", lambda _: "C:/jine/claude.exe")
    assert najdi_program("claude", str(program)) == program


def test_najdi_program_nastaveny_nazev_hleda_v_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: "C:/bin/x.exe" if n == "x" else None)
    assert najdi_program("claude", "x") == Path("C:/bin/x.exe")


def test_najdi_program_vychozi_z_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: "C:/bin/claude.exe" if n == "claude" else None)
    assert najdi_program("claude", None) == Path("C:/bin/claude.exe")


def test_najdi_program_nenalezeno(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    assert najdi_program("claude", None) is None
    assert najdi_program("claude", "neexistuje") is None


def test_nativni_codex_z_npm_spoustece(tmp_path):
    exe = tmp_path / NATIVNI
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    cmd = tmp_path / "codex.cmd"
    cmd.write_text("")
    assert nativni_codex(cmd) == exe


def test_nativni_codex_bez_exe_vrati_spoustec(tmp_path):
    cmd = tmp_path / "codex.cmd"
    cmd.write_text("")
    assert nativni_codex(cmd) == cmd


def test_nativni_codex_ignoruje_jine_programy(tmp_path):
    exe = tmp_path / "codex.exe"
    assert nativni_codex(exe) == exe


def test_docasne_adresare_prace_je_prazdna_a_zmizi():
    with docasne_adresare() as (prace, soubory):
        assert prace.is_dir() and soubory.is_dir() and not any(prace.iterdir())
        koren = prace.parent
        assert prace != soubory
    assert not koren.exists()


def test_conftest_blokuje_skutecny_nastroj():
    with pytest.raises(RuntimeError, match="skutečný nástroj"):
        podproces.spust(["claude"], "", {}, Path("."), 1)


def test_timeout_zabije_osirele_potomky_drzici_stdout(tmp_path):
    """Prostřední proces skončí hned, potomek drží stdout (taskkill /T už strom nenajde)."""
    skript = _skript(tmp_path, "import subprocess, sys\n"
                               "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(25)'])\n")
    start = time.monotonic()
    with pytest.raises(VyprselCas):
        spust_proces([sys.executable, str(skript)], "", ciste_prostredi(), tmp_path, 2)
    assert time.monotonic() - start < 12


def test_timeout_plati_i_kdyz_potomek_necte_velky_stdin(tmp_path):
    skript = _skript(tmp_path, "import time\ntime.sleep(25)\n")
    start = time.monotonic()
    with pytest.raises(VyprselCas):
        spust_proces([sys.executable, str(skript)], "x" * 2_000_000, ciste_prostredi(), tmp_path, 1)
    assert time.monotonic() - start < 12

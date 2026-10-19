import sys
import time
from pathlib import Path

import pytest

from refiner.models import subprocess
from refiner.models.subprocess import (
    REMOVE,
    ProcessTimeout,
    clean_environment,
    temporary_directories,
    find_program,
    native_codex,
    run_process,
)

NATIVE = Path("node_modules/@openai/codex/node_modules/@openai/codex-win32-x64"
               "/vendor/x86_64-pc-windows-msvc/bin/codex.exe")


def _script(tmp_path, returncode):
    path = tmp_path / "skript.py"
    path.write_text(returncode, encoding="utf-8")
    return path


def test_clean_environment_removes_keys():
    env = clean_environment({"ANTHROPIC_API_KEY": "sk-a", "anthropic_api_key": "sk-b", "OPENAI_API_KEY": "x",
                           "CODEX_API_KEY": "x", "CLAUDE_CODE_OAUTH_TOKEN": "x", "CLAUDE_CODE_SIMPLE": "1",
                           "CLAUDECODE": "1", "CLAUDE_CONFIG_DIR": "C:/c", "CODEX_HOME": "C:/x", "PATH": "p"},
                          extra={"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"})
    assert env == {"CLAUDE_CONFIG_DIR": "C:/c", "CODEX_HOME": "C:/x", "PATH": "p",
                   "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"}


def test_clean_environment_reads_os_environ_and_removes_other_provider_variables(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-a")
    monkeypatch.setenv("openai_api_key", "sk-b")
    monkeypatch.setenv("ANTHROPIC_CUSTOM_HEADERS", "x")
    monkeypatch.setenv("OPENAI_ORG_ID", "x")
    env = clean_environment()
    assert not [k for k in env if k.upper().startswith(("ANTHROPIC_", "OPENAI_"))]


def test_extra_cannot_restore_key():
    with pytest.raises(ValueError):
        clean_environment({}, extra={"anthropic_api_key": "sk-x"})


def test_remove_contains_all_documented_variables():
    assert {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY",
            "CODEX_ACCESS_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "ANTHROPIC_BASE_URL", "OPENAI_BASE_URL",
            "CLAUDE_CODE_EFFORT_LEVEL", "ANTHROPIC_MODEL", "OPENAI_IDENTITY_TOKEN_FILE"} <= set(REMOVE)


def test_long_utf8_stdin_with_accents(tmp_path):
    script = _script(tmp_path, "import sys\n"
                               "data = sys.stdin.buffer.read()\n"
                               "sys.stdout.buffer.write(data)\n")
    text = "Příliš žluťoučký kůň úpěl ďábelské ódy. " * 5000   # ~200,000 characters
    v = run_process([sys.executable, str(script)], text, clean_environment(), tmp_path, 30)
    assert v.returncode == 0 and v.stdout == text


def test_env_and_cwd_are_forwarded(tmp_path):
    script = _script(tmp_path, "import os, sys\n"
                               "sys.stdout.write(os.getcwd() + '|' + os.environ.get('X', ''))\n")
    work = tmp_path / 'work'
    work.mkdir()
    env = clean_environment(extra={"X": "hodnota"})
    v = run_process([sys.executable, str(script)], "", env, work, 30)
    assert v.returncode == 0 and v.stdout == f"{work.resolve()}|hodnota"


def test_nonzero_returncode_and_stderr(tmp_path):
    script = _script(tmp_path, "import sys\nsys.stderr.write('chyba')\nsys.exit(3)\n")
    v = run_process([sys.executable, str(script)], "", clean_environment(), tmp_path, 30)
    assert (v.returncode, v.stderr) == (3, "chyba")


def test_missing_program_raises_filenotfound(tmp_path):
    with pytest.raises(FileNotFoundError):
        run_process([str(tmp_path / "neexistuje.exe")], "", clean_environment(), tmp_path, 5)


def test_timeout_kills_descendant_processes(tmp_path):
    script = _script(tmp_path, "import subprocess, sys, time\n"
                               "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                               "time.sleep(60)\n")
    start = time.monotonic()
    with pytest.raises(ProcessTimeout):
        run_process([sys.executable, str(script)], "", clean_environment(), tmp_path, 1)
    assert time.monotonic() - start < 15


def test_find_program_prefers_configured_path(tmp_path, monkeypatch):
    program = tmp_path / "muj-claude.exe"
    program.write_text("")
    monkeypatch.setattr("shutil.which", lambda _: "C:/jine/claude.exe")
    assert find_program("claude", str(program)) == program


def test_find_program_looks_up_configured_name_in_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: "C:/bin/x.exe" if n == "x" else None)
    assert find_program("claude", "x") == Path("C:/bin/x.exe")


def test_find_program_default_from_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: "C:/bin/claude.exe" if n == "claude" else None)
    assert find_program("claude", None) == Path("C:/bin/claude.exe")


def test_find_program_not_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    assert find_program("claude", None) is None
    assert find_program("claude", "neexistuje") is None


def test_native_codex_from_npm_launcher(tmp_path):
    exe = tmp_path / NATIVE
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    cmd = tmp_path / "codex.cmd"
    cmd.write_text("")
    assert native_codex(cmd) == exe


def test_native_codex_without_exe_returns_launcher(tmp_path):
    cmd = tmp_path / "codex.cmd"
    cmd.write_text("")
    assert native_codex(cmd) == cmd


def test_native_codex_ignores_other_programs(tmp_path):
    exe = tmp_path / "codex.exe"
    assert native_codex(exe) == exe


def test_temporary_work_directory_is_empty_and_removed():
    with temporary_directories() as (work, files):
        assert work.is_dir() and files.is_dir() and not any(work.iterdir())
        root = work.parent
        assert work != files
    assert not root.exists()


def test_conftest_blocks_real_cli():
    with pytest.raises(RuntimeError, match="real provider CLI"):
        subprocess.run(["claude"], "", {}, Path("."), 1)


def test_timeout_kills_orphaned_descendants_holding_stdout(tmp_path):
    """The parent exits immediately while a descendant holds stdout; taskkill /T misses it."""
    script = _script(tmp_path, "import subprocess, sys\n"
                               "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(25)'])\n")
    start = time.monotonic()
    with pytest.raises(ProcessTimeout):
        run_process([sys.executable, str(script)], "", clean_environment(), tmp_path, 2)
    assert time.monotonic() - start < 12


def test_timeout_applies_when_child_does_not_read_large_stdin(tmp_path):
    script = _script(tmp_path, "import time\ntime.sleep(25)\n")
    start = time.monotonic()
    with pytest.raises(ProcessTimeout):
        run_process([sys.executable, str(script)], "x" * 2_000_000, clean_environment(), tmp_path, 1)
    assert time.monotonic() - start < 12

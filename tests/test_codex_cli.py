import json
import logging
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai.lib._pydantic import to_strict_json_schema

from refiner.data import Evaluation, SuggestionReview as SuggestionReview, TokenUsage, RequirementsOutput
from refiner.configuration import load_settings
from refiner.steps import with_repair as with_repair
from refiner.models.errors import ModelError
from refiner.models.codex_cli import CodexModel, codex_error_kind, read_events
from refiner.models.subprocess import ProcessTimeout, ProcessResult
from refiner.porovnani import Coverage as Coverage, ReferenceElements as ReferenceElements, PairComparison as PairComparison

ROOT = Path(__file__).parent.parent

REQUIREMENTS = {'requirements': [{"id": "N1", "text": "Metodika", 'citation': "popis metodiky"}]}
USAGE = {"input_tokens": 2000, "cached_input_tokens": 500, "output_tokens": 300,
         "reasoning_output_tokens": 100}
LOGIN_OK = ProcessResult(0, "", "Logged in using ChatGPT\n")


def events(*items) -> str:
    return "\n".join(p if isinstance(p, str) else json.dumps(p) for p in items) + "\n"


def success(usage=USAGE) -> str:
    return events({"type": "thread.started", "thread_id": "t"},
                    {"type": "item.completed", "item": {"type": "agent_message", "text": "hotovo"}},
                    {"type": "turn.completed", "usage": usage})


def ok_result(stdout=None) -> ProcessResult:
    return ProcessResult(0, success() if stdout is None else stdout, "")


def settings():
    return load_settings(ROOT / "settings.yaml").models


class FakeRunner:
    """login status returns LOGIN_OK; other calls consume (ProcessResult, output-file content) pairs."""

    def __init__(self, *responses, login=LOGIN_OK):
        self.queue = list(responses)
        self.login = login
        self.calls = []
        self.login_calls = []

    def __call__(self, argv, stdin, env, cwd, timeout):
        if argv[1:3] == ["login", "status"]:
            self.login_calls.append(SimpleNamespace(argv=argv, env=env, cwd=cwd, timeout=timeout))
            return self.login
        files = {}
        output = Path(argv[argv.index("-o") + 1])
        for p in output.parent.iterdir():
            files[p.name] = p.read_text(encoding="utf-8")
        self.calls.append(SimpleNamespace(
            argv=argv, stdin=stdin, env=env, cwd=Path(cwd), timeout=timeout, files=files,
            work_contents=list(Path(cwd).iterdir())))
        response = self.queue.pop(0)
        if isinstance(response, Exception):
            raise response
        result, content = response if isinstance(response, tuple) else (response, None)
        if content is not None:
            output.write_text(content, encoding="utf-8")
        return result


@pytest.fixture(autouse=True)
def _codex_in_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: "C:/fake/codex.exe" if n == "codex" else None)


def model(*responses, **kw):
    runner = FakeRunner(*responses, **kw)
    return CodexModel(settings(), run=runner), runner


def json_response(content=REQUIREMENTS, stdout=None):
    return (ok_result(stdout), json.dumps(content))


def call_json(m, step='evaluation_1'):
    return m.json("INSTRUKCE", "ZADANI-123", RequirementsOutput, step=step)


def test_argv_isolation_and_stdin():
    m, s = model(json_response())
    call_json(m)
    v = s.calls[0]
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


def test_instructions_in_file_and_toml_path(monkeypatch, tmp_path):
    tomllib = pytest.importorskip("tomllib")
    directory = tmp_path / "O'Brien Novák"
    directory.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(directory))
    m, s = model(json_response())
    call_json(m)
    argv = s.calls[0].argv
    value = next(a for a in argv if a.startswith("model_instructions_file="))
    path = tomllib.loads(value)["model_instructions_file"]
    assert "O'Brien Novák" in path
    assert s.calls[0].files['instructions.md'] == "INSTRUKCE"
    assert Path(path).name == 'instructions.md'


def test_schema_is_strict():
    m, s = model(json_response())
    call_json(m)
    argv = s.calls[0].argv
    assert "--output-schema" in argv
    sch = json.loads(s.calls[0].files["schema.json"])
    assert sch["additionalProperties"] is False and set(sch["required"]) == set(sch["properties"])
    assert Path(argv[argv.index("--output-schema") + 1]).name == "schema.json"


def test_text_without_schema():
    m, s = model((ok_result(), "Ahoj světe"))
    assert m.text("I", "Z", step='suggestion') == "Ahoj světe"
    assert "--output-schema" not in s.calls[0].argv


def test_effort_from_configuration_ignores_parameter():
    m, s = model(json_response())
    m.json("I", "Z", RequirementsOutput, step="k", effort="low")
    assert "model_reasoning_effort=high" in s.calls[0].argv


def test_strict_schema_for_all_project_schemas():
    for c in (RequirementsOutput, Evaluation, SuggestionReview, PairComparison, ReferenceElements, Coverage):
        to_strict_json_schema(c)


def test_environment_without_keys(monkeypatch):
    monkeypatch.setenv("CODEX_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-y")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-z")
    monkeypatch.setenv("codex_access_token", "t")
    monkeypatch.setenv("CODEX_HOME", "C:/codex-home")
    m, s = model(json_response())
    call_json(m)
    for env in (s.calls[0].env, s.login_calls[0].env):
        assert not {"CODEX_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CODEX_ACCESS_TOKEN"} \
            & {k.upper() for k in env}
        assert env["CODEX_HOME"] == "C:/codex-home"


def test_cwd_empty_and_removed_after_call():
    m, s = model(json_response())
    call_json(m)
    v = s.calls[0]
    assert v.work_contents == [] and not v.cwd.exists()
    assert v.timeout == settings().timeout_s


def test_json_success_and_usage():
    m, _ = model(json_response())
    assert call_json(m) == RequirementsOutput.model_validate(REQUIREMENTS)
    assert m.take_usage() == [TokenUsage(step='evaluation_1', model="gpt-6-astra", input_tokens=2000, output_tokens=300,
                                              cache_read_tokens=500, subscription=True)]
    assert m.take_usage() == []


def test_non_json_stdout_lines_are_skipped():
    stdout = events("WARNING: něco se děje", "", {"type": "thread.started"}, "[1, 2]", "{rozbite",
                      {"type": "turn.completed", "usage": USAGE})
    m, _ = model(json_response(stdout=stdout))
    assert call_json(m) == RequirementsOutput.model_validate(REQUIREMENTS)
    assert m.take_usage()[0].input_tokens == 2000


def test_missing_output_file_is_invalid():
    m, _ = model(ok_result())
    with pytest.raises(ModelError) as e:
        call_json(m)
    assert e.value.kind == 'invalid_output' and e.value.service == "Codex"


def test_empty_text_output_file_is_other():
    m, _ = model((ok_result(), "  \n"))
    with pytest.raises(ModelError) as e:
        m.text("I", "Z", step='suggestion')
    assert e.value.kind == 'other'


def test_invalid_json_triggers_repair():
    m, s = model((ok_result(), '{"nalezitosti": "ne seznam"}'), json_response())
    v = with_repair(m, "ZADANI", lambda z: m.json("I", z, RequirementsOutput, step="k"), lambda _: [], lambda _: "")
    assert v == RequirementsOutput.model_validate(REQUIREMENTS) and len(s.calls) == 2
    assert "## Oprava" in s.calls[1].stdin


def test_truncated_json_is_truncated():
    m, _ = model((ok_result(), '{"nalezitosti": [{"id": "N1"'))
    with pytest.raises(ModelError) as e:
        call_json(m)
    assert e.value.kind == 'truncated'


@pytest.mark.parametrize('text,kind', [
    ("You’ve hit your usage limit. Visit https://chatgpt.com/settings/usage to purchase more credits",
     'subscription_limit'),
    ("usage_limit_reached", 'subscription_limit'),
    ("quota_exceeded", 'subscription_limit'),
    ("Not signed in. Please run 'codex login' to sign in with ChatGPT", 'not_authenticated'),
    ("The 'gpt-x' model is not supported when using Codex with a ChatGPT account.", 'model_unavailable'),
    ("rate_limit_exceeded", 'overloaded'),
    ("server_overloaded", 'overloaded'),
    ("něco jiného", None),
])
def test_codex_error_kind(text, kind):
    assert codex_error_kind(text) == kind


def test_turn_failed_maps_error():
    stdout = events({"type": "thread.started"},
                      {"type": "turn.failed", "error": {"message": "You’ve hit your usage limit. Try later."}})
    m, _ = model(ProcessResult(1, stdout, ""))
    with pytest.raises(ModelError) as e:
        call_json(m)
    assert e.value.kind == 'subscription_limit' and e.value.service == "Codex"
    assert "usage limit" in e.value.message


def test_unavailable_model_names_model():
    stdout = events({"type": "error", "message": "The 'gpt-6-astra' model is not supported when using "
                                                   "Codex with a ChatGPT account."})
    m, _ = model(ProcessResult(1, stdout, ""))
    with pytest.raises(ModelError) as e:
        call_json(m)
    assert e.value.kind == 'model_unavailable' and "gpt-6-astra" in e.value.message


def test_stderr_error_with_nonzero_returncode():
    m, _ = model(ProcessResult(1, "", "Not signed in. Please run 'codex login'"))
    with pytest.raises(ModelError) as e:
        call_json(m)
    assert e.value.kind == 'not_authenticated'


def test_context_window_exceeded_is_other_with_explanation():
    stdout = events({"type": "turn.failed", "error": {"message": "context_window_exceeded"}})
    m, _ = model(ProcessResult(1, stdout, ""))
    with pytest.raises(ModelError) as e:
        call_json(m)
    assert e.value.kind == 'other' and "příliš dlouhé" in e.value.message


def test_unknown_error_is_other_without_keys():
    m, _ = model(ProcessResult(1, "", "boom sk-abc123"))
    with pytest.raises(ModelError) as e:
        call_json(m)
    assert e.value.kind == 'other' and "sk-abc123" not in e.value.message


def test_error_with_usage_records_usage():
    stdout = events({"type": "turn.completed", "usage": USAGE},
                      {"type": "turn.failed", "error": {"message": "server_overloaded"}})
    m, _ = model(ProcessResult(1, stdout, ""))
    with pytest.raises(ModelError):
        call_json(m)
    assert len(m.take_usage()) == 1


def test_transient_stream_error_preserves_success():
    stdout = events({"type": "error", "message": "Reconnecting... 1/5"},
                      {"type": "turn.completed", "usage": USAGE})
    m, _ = model(json_response(stdout=stdout))
    assert call_json(m) == RequirementsOutput.model_validate(REQUIREMENTS)


def test_tool_use_only_warns(caplog):
    stdout = events({"type": "item.completed", "item": {"type": "command_execution", "command": "ls"}},
                      {"type": "turn.completed", "usage": USAGE})
    m, _ = model(json_response(stdout=stdout))
    with caplog.at_level(logging.WARNING, logger="refiner.models.codex_cli"):
        assert call_json(m) == RequirementsOutput.model_validate(REQUIREMENTS)
    assert "command_execution" in caplog.text


def test_read_events():
    stdout = events({"type": "item.started", "item": {"type": "reasoning"}},
                      {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 2}},
                      {"type": "turn.completed", "usage": {"input_tokens": 10, "cached_input_tokens": 4,
                                                           "output_tokens": 20}},
                      {"type": "turn.failed", "error": {"message": "a"}},
                      {"type": "error", "message": "b"})
    usage, messages, types = read_events(stdout)
    assert usage == {"input_tokens": 11, "cached_input_tokens": 4, "output_tokens": 22}
    assert messages == ["a", "b"] and types == {"reasoning"}
    assert read_events("nic\n") == (None, [], set())


@pytest.mark.parametrize("login", [
    ProcessResult(0, "", "Logged in using an API key - sk-***"),
    ProcessResult(1, "", "Not logged in"),
    ProcessResult(0, "", ""),
])
def test_login_status_rejects_other_authentication(login):
    with pytest.raises(ModelError) as e:
        model(login=login)
    assert e.value.kind == 'not_authenticated' and e.value.service == "Codex"


def test_login_status_redacts_api_key_in_detail():
    with pytest.raises(ModelError) as e:
        model(login=ProcessResult(0, "", "Logged in using an API key - sk-abc123"))
    assert "sk-abc123" not in e.value.detail and "sk-abc123" not in e.value.message


def test_login_status_success_on_stdout():
    model(login=ProcessResult(0, "Logged in using ChatGPT", ""))


def test_native_exe_instead_of_cmd(monkeypatch, tmp_path):
    exe = (tmp_path / "node_modules/@openai/codex/node_modules/@openai/codex-win32-x64"
           "/vendor/x86_64-pc-windows-msvc/bin/codex.exe")
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    cmd = tmp_path / "codex.cmd"
    cmd.write_text("")
    monkeypatch.setattr("shutil.which", lambda n: str(cmd) if n == "codex" else None)
    m, s = model(json_response())
    call_json(m)
    assert s.calls[0].argv[0] == str(exe) and s.login_calls[0].argv[0] == str(exe)


def test_timeout():
    m, _ = model(ProcessTimeout())
    with pytest.raises(ModelError) as e:
        call_json(m)
    assert e.value.kind == 'timeout' and e.value.service == "Codex"


def test_not_installed(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    with pytest.raises(ModelError) as e:
        CodexModel(settings(), run=FakeRunner())
    assert e.value.kind == 'not_installed' and "příkaz codex nebyl nalezen" in e.value.message


def test_not_installed_at_execution():
    m, _ = model(FileNotFoundError())
    with pytest.raises(ModelError) as e:
        call_json(m)
    assert e.value.kind == 'not_installed'


def test_argv_omits_unknown_codex_settings():
    """An earlier live test with codex-cli 0.163.0 rejected tools.view_image as an unknown setting."""
    m, s = model(json_response())
    call_json(m)
    assert not any(a.startswith("tools.") for a in s.calls[0].argv)


def test_codex_item_error_warning_preserves_call():
    """An earlier live capture reports configuration warnings as item.completed with type error."""
    warning = {"type": "item.completed", "item": {
        "id": "item_0", "type": "error",
        "message": "Codex is ignoring 1 unrecognized configuration setting. Check for typos or deprecated settings."}}
    stdout = events({"type": "thread.started", "thread_id": "t"}, warning, warning, {"type": "turn.started"},
                      {"type": "item.completed", "item": {"id": "item_2", "type": "agent_message", "text": "{}"}},
                      {"type": "turn.completed", "usage": {**USAGE, "cache_write_input_tokens": 0}})
    m, _ = model(json_response(stdout=stdout))
    assert call_json(m) == RequirementsOutput.model_validate(REQUIREMENTS)
    assert m.take_usage()[0].input_tokens == 2000

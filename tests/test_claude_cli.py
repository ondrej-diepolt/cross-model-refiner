import json
import logging
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from refiner.data import TokenUsage, RequirementsOutput
from refiner.configuration import load_settings
from refiner.steps import with_repair as with_repair
from refiner.models.errors import ModelError
from refiner.models.claude_cli import ClaudeCliModel, claude_error_kind
from refiner.models.subprocess import ProcessTimeout, ProcessResult

ROOT = Path(__file__).parent.parent

REQUIREMENTS = {'requirements': [{"id": "N1", "text": "Metodika", 'citation': "popis metodiky"}]}
USAGE = {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 30,
         "cache_creation_input_tokens": 20}
OK_JSON = {"type": "result", "subtype": "success", "is_error": False, "result": "hotovo",
           "structured_output": REQUIREMENTS, "stop_reason": "end_turn", "usage": USAGE}
AUTH_OK = ProcessResult(0, json.dumps({"loggedIn": True, "authMethod": "claude.ai",
                                  "apiProvider": "firstParty"}), "")


def ok(**changes) -> ProcessResult:
    return ProcessResult(0, json.dumps({**OK_JSON, **changes}), "")


def settings():
    return load_settings(ROOT / "settings.yaml").models


class FakeRunner:
    """Dispatch by argv: auth status returns AUTH_OK; other calls consume queued responses."""

    def __init__(self, *responses, auth=AUTH_OK):
        self.queue = list(responses)
        self.auth = auth
        self.calls = []
        self.auth_calls = []

    def __call__(self, argv, stdin, env, cwd, timeout):
        if argv[1:3] == ["auth", "status"]:
            self.auth_calls.append(SimpleNamespace(argv=argv, env=env, cwd=cwd, timeout=timeout))
            return self.auth
        files = {}
        if "--system-prompt-file" in argv:
            directory = Path(argv[argv.index("--system-prompt-file") + 1]).parent
            files = {p.name: p.read_text(encoding="utf-8") for p in directory.iterdir()}
        self.calls.append(SimpleNamespace(
            argv=argv, stdin=stdin, env=env, cwd=Path(cwd), timeout=timeout, files=files,
            work_contents=list(Path(cwd).iterdir())))
        response = self.queue.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture(autouse=True)
def _claude_in_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: "C:/fake/claude.exe" if n == "claude" else None)


def model(*responses, **kw):
    runner = FakeRunner(*responses, **kw)
    return ClaudeCliModel(settings(), run=runner), runner


def call_json(m, **kw):
    return m.json("INSTRUKCE", "ZADANI-123", RequirementsOutput, step='requirements', **kw)


def test_task_only_in_stdin_and_instructions_in_file():
    m, s = model(ok())
    call_json(m)
    v = s.calls[0]
    assert "ZADANI-123" in v.stdin and not any("ZADANI-123" in a for a in v.argv)
    assert v.files['instructions.md'] == "INSTRUKCE"
    assert not any("INSTRUKCE" in a for a in v.argv)


def test_isolation_flags():
    m, s = model(ok())
    call_json(m)
    argv = s.calls[0].argv
    for p in ["-p", "--output-format", "json", "--no-session-persistence", "--safe-mode",
              "--strict-mcp-config", "--permission-prompts"]:
        assert p in argv
    assert argv[argv.index("--tools") + 1] == "" and "--bare" not in argv
    assert argv[argv.index("--disallowedTools") + 1] == "mcp__*"
    assert argv[argv.index("--model") + 1] == "claude-opus-5-5"
    schema = json.loads(argv[argv.index("--json-schema") + 1])
    assert schema == RequirementsOutput.model_json_schema()


def test_model_and_effort_from_configuration_and_extraction():
    m, s = model(ok(), ok(), ok(result="text"))
    call_json(m)
    call_json(m, effort="low")
    m.text("I", "Z", step='suggestion')
    efforts = [v.argv[v.argv.index("--effort") + 1] for v in s.calls]
    assert efforts == ["high", "low", "high"]
    assert "--json-schema" not in s.calls[2].argv


def test_environment_without_keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-y")
    monkeypatch.setenv("CLAUDE_CODE_SIMPLE", "1")
    monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", "low")
    monkeypatch.setenv("Anthropic_Auth_Token", "t")
    m, s = model(ok())
    call_json(m)
    for env in (s.calls[0].env, s.auth_calls[0].env):
        assert not {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CLAUDE_CODE_SIMPLE", "CLAUDE_CODE_EFFORT_LEVEL",
                    "ANTHROPIC_AUTH_TOKEN"} & {k.upper() for k in env}
        assert env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
        assert env["CLAUDE_CODE_DISABLE_ATTACHMENTS"] == "1"
        assert env["CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS"] == "1"


def test_cwd_empty_and_removed_after_call():
    m, s = model(ok())
    call_json(m)
    v = s.calls[0]
    assert v.work_contents == [] and not v.cwd.exists()
    assert s.calls[0].timeout == settings().timeout_s


def test_json_success_and_usage():
    m, _ = model(ok())
    assert call_json(m) == RequirementsOutput.model_validate(REQUIREMENTS)
    assert m.take_usage() == [TokenUsage(step='requirements', model="claude-opus-5-5", input_tokens=100,
                                              output_tokens=50, cache_read_tokens=30, cache_write_tokens=20, subscription=True)]
    assert m.take_usage() == []


def test_text_returns_result():
    m, _ = model(ok(result="Ahoj světe"))
    assert m.text("I", "Z", step='suggestion') == "Ahoj světe"


def test_json_without_structured_output_is_invalid():
    response = {k: v for k, v in OK_JSON.items() if k != "structured_output"}
    m, _ = model(ProcessResult(0, json.dumps(response), ""))
    with pytest.raises(ModelError) as e:
        call_json(m)
    assert e.value.kind == 'invalid_output' and e.value.service == "Claude Code"


def test_json_exhausted_schema_retries_is_invalid():
    response = {"type": "result", "subtype": "error_max_structured_output_retries", "is_error": True,
           "errors": ["x"], "usage": USAGE}
    m, _ = model(ProcessResult(1, json.dumps(response), ""))
    with pytest.raises(ModelError) as e:
        call_json(m)
    assert e.value.kind == 'invalid_output'
    assert len(m.take_usage()) == 1   # tokens are billed on errors too


def test_json_schema_failure_triggers_repair():
    invalid = ok(structured_output={'requirements': "ne seznam"})
    m, s = model(invalid, ok())
    v = with_repair(m, "ZADANI", lambda z: m.json("I", z, RequirementsOutput, step='requirements'),
                  lambda _: [], lambda _: "")
    assert v == RequirementsOutput.model_validate(REQUIREMENTS) and len(s.calls) == 2
    assert "## Oprava" in s.calls[1].stdin


def test_truncation_and_refusal():
    m, _ = model(ok(stop_reason="max_tokens"), ok(stop_reason="refusal"))
    with pytest.raises(ModelError) as e:
        call_json(m)
    assert e.value.kind == 'truncated' and "uříznutá" in e.value.message
    with pytest.raises(ModelError) as e:
        call_json(m)
    assert e.value.kind == 'refused'


@pytest.mark.parametrize('text,kind', [
    ("Not logged in · Please run /login", 'not_authenticated'),
    ("Login expired · Please run /login", 'not_authenticated'),
    ("Failed to authenticate. API Error: 401 OAuth token has expired", 'not_authenticated'),
    ("You've hit your session limit · resets 3:45pm", 'subscription_limit'),
    ("You've hit your weekly limit · resets Mon 12:00am", 'subscription_limit'),
    ("Request rejected (429)", 'overloaded'),
    ("Server is temporarily limiting requests", 'overloaded'),
    ("Claude Opus is not available with the Claude Pro plan", 'model_unavailable'),
    ("Model claude-x is not a recognized model id", 'model_unavailable'),
    ("něco úplně jiného", None),
])
def test_claude_error_kind(text, kind):
    assert claude_error_kind(text) == kind


@pytest.mark.parametrize('text,kind', [
    ("Not logged in · Please run /login", 'not_authenticated'),
    ("You've hit your session limit · resets 3:45pm", 'subscription_limit'),
    ("Claude Opus is not available with the Claude Pro plan", 'model_unavailable'),
    ("Request rejected (429)", 'overloaded'),
])
def test_plain_text_with_nonzero_returncode(text, kind):
    m, _ = model(ProcessResult(1, text, ""))
    with pytest.raises(ModelError) as e:
        call_json(m)
    assert e.value.kind == kind and e.value.service == "Claude Code"


def test_limit_and_model_include_detail():
    m, _ = model(ProcessResult(1, "You've hit your session limit · resets 3:45pm", ""),
                 ProcessResult(1, "Claude Opus is not available with the Claude Pro plan", ""))
    with pytest.raises(ModelError) as e:
        call_json(m)
    assert "resets 3:45pm" in e.value.message
    with pytest.raises(ModelError) as e:
        call_json(m)
    assert "claude-opus-5-5" in e.value.message


def test_json_envelope_error_is_mapped():
    response = {"type": "result", "subtype": "success", "is_error": True, "usage": USAGE,
           "result": "You've hit your weekly limit · resets Mon 12:00am"}
    m, _ = model(ProcessResult(1, json.dumps(response), ""))
    with pytest.raises(ModelError) as e:
        call_json(m)
    assert e.value.kind == 'subscription_limit'


def test_connection_error_is_network():
    response = {"type": "result", "subtype": "error_during_execution", "is_error": True, "usage": USAGE,
           "result": "API Error: connect ECONNRESET"}
    m, _ = model(ProcessResult(1, json.dumps(response), ""))
    with pytest.raises(ModelError) as e:
        call_json(m)
    assert e.value.kind == 'network'


def test_unknown_error_is_other_without_keys():
    m, _ = model(ProcessResult(1, "boom sk-abc123", "stderr sk-def456"))
    with pytest.raises(ModelError) as e:
        call_json(m)
    assert e.value.kind == 'other' and "sk-abc123" not in e.value.message and "sk-def456" not in e.value.message


def test_non_json_with_zero_returncode_is_other():
    m, _ = model(ProcessResult(0, "to není json", ""))
    with pytest.raises(ModelError) as e:
        call_json(m)
    assert e.value.kind == 'other'


def test_timeout():
    m, _ = model(ProcessTimeout())
    with pytest.raises(ModelError) as e:
        call_json(m)
    assert e.value.kind == 'timeout' and e.value.service == "Claude Code"


def test_not_installed_in_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    with pytest.raises(ModelError) as e:
        ClaudeCliModel(settings(), run=FakeRunner())
    assert e.value.kind == 'not_installed' and "příkaz claude nebyl nalezen" in e.value.message


def test_not_installed_at_execution():
    m, _ = model(FileNotFoundError())
    with pytest.raises(ModelError) as e:
        call_json(m)
    assert e.value.kind == 'not_installed'


def test_command_from_settings(tmp_path):
    program = tmp_path / "muj-claude.exe"
    program.write_text("")
    n = settings()
    n = n.model_copy(update={"subscription": n.subscription.model_copy(
        update={"claude": n.subscription.claude.model_copy(update={"command": str(program)})})})
    s = FakeRunner(ok())
    ClaudeCliModel(n, run=s).json("I", "Z", RequirementsOutput, step="k")
    assert s.calls[0].argv[0] == str(program) and s.auth_calls[0].argv[0] == str(program)


def test_api_key_login_is_rejected():
    auth = ProcessResult(0, json.dumps({"loggedIn": True, "authMethod": "api_key"}), "")
    with pytest.raises(ModelError) as e:
        model(auth=auth)
    assert e.value.kind == 'not_authenticated' and "api_key" in e.value.detail


@pytest.mark.parametrize("auth", [
    ProcessResult(0, json.dumps({"loggedIn": False}), ""),
    ProcessResult(1, "Not logged in", ""),
    ProcessResult(0, "[]", ""),
])
def test_unauthenticated_or_unreadable_status(auth):
    with pytest.raises(ModelError) as e:
        model(auth=auth)
    assert e.value.kind == 'not_authenticated'


def test_login_check_uses_empty_directory_and_timeout():
    m, s = model()
    a = s.auth_calls[0]
    assert a.timeout == 60 and a.argv[1:] == ["auth", "status"]


def test_path_with_space_and_apostrophe(monkeypatch, tmp_path):
    directory = tmp_path / "O'Brien Novák"
    directory.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(directory))
    m, s = model(ok())
    call_json(m)
    v = s.calls[0]
    assert v.files['instructions.md'] == "INSTRUKCE"
    assert "O'Brien Novák" in v.argv[v.argv.index("--system-prompt-file") + 1]


def test_debug_log_omits_instructions(caplog):
    m, _ = model(ok())
    with caplog.at_level(logging.DEBUG, logger="refiner.models.claude_cli"):
        call_json(m)
    assert "INSTRUKCE" not in caplog.text and "ZADANI-123" not in caplog.text

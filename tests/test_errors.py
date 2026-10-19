import anthropic
import httpx2
import openai
import pytest

from refiner.models.errors import ModelError, convert_exception

REQ = httpx2.Request("POST", "https://api.example/v1")


def resp(code):
    return httpx2.Response(code, request=REQ)


@pytest.mark.parametrize('exc,service,kind', [
    (anthropic.AuthenticationError("x", response=resp(401), body=None), "Anthropic", 'authentication'),
    (anthropic.RateLimitError("x", response=resp(429), body=None), "Anthropic", 'overloaded'),
    (anthropic.InternalServerError("x", response=resp(529), body=None), "Anthropic", 'overloaded'),
    (anthropic.APITimeoutError(request=REQ), "Anthropic", 'timeout'),
    (anthropic.APIConnectionError(request=REQ), "Anthropic", 'network'),
    (anthropic.BadRequestError("Your credit balance is too low", response=resp(400), body=None), "Anthropic", 'credit'),
    (openai.AuthenticationError("x", response=resp(401), body=None), "OpenAI", 'authentication'),
    (openai.RateLimitError("x", response=resp(429), body={"code": "insufficient_quota"}), "OpenAI", 'credit'),
    (openai.RateLimitError("x", response=resp(429), body={"code": "rate_limit_exceeded"}), "OpenAI", 'overloaded'),
    (openai.APITimeoutError(request=REQ), "OpenAI", 'timeout'),
    (ValueError("??"), "OpenAI", 'other'),
])
def test_convert_exception(exc, service, kind):
    assert convert_exception(exc, service).kind == kind


def test_authentication_message_names_variable():
    assert "OPENAI_API_KEY" in ModelError('authentication', "OpenAI").message


def test_truncated_message_explains_limits():
    claude = ModelError('truncated', "Anthropic").message
    gpt = ModelError('truncated', "OpenAI").message
    assert "uříznutá" in claude and "nastaveni.yaml" in claude and "pokracovat.bat" in claude
    assert "max_tokens_json" in claude and "max_output_tokens" not in claude
    assert "max_output_tokens" in gpt and "max_tokens_json" not in gpt
    assert "ani po opakování" not in claude


def test_refusal_message_with_category():
    assert "cyber" in ModelError('refused', "Anthropic", "cyber").message


def test_model_error_passes_through_unchanged():
    error = ModelError('network', "OpenAI")
    assert convert_exception(error, "OpenAI") is error


def test_detail_does_not_contain_key():
    exc = openai.AuthenticationError(
        "Incorrect API key provided: sk-proj-****abcd and sk-ant-api03-XYZ_12",
        response=resp(401), body=None)
    e = convert_exception(exc, "OpenAI")
    assert "sk-proj" not in e.detail and "abcd" not in e.detail and "XYZ" not in e.detail
    assert "sk-" in e.detail


@pytest.mark.parametrize('service,command', [("Claude Code", "claude"), ("Codex", "codex")])
def test_not_installed_names_command(service, command):
    h = ModelError('not_installed', service).message
    assert f"příkaz {command} nebyl nalezen" in h and "modely.rezim na api" in h


def test_unauthenticated_codex_explains_login():
    assert "codex login" in ModelError('not_authenticated', "Codex").message


def test_unauthenticated_claude_explains_login():
    assert "/login" in ModelError('not_authenticated', "Claude Code").message


def test_limit_includes_tool_text():
    h = ModelError('subscription_limit', "Claude Code", "You've hit your session limit · resets 3:45pm").message
    assert "resets 3:45pm" in h and "pokracovat.bat" in h


def test_unavailable_model_names_model():
    assert "gpt-6-astra" in ModelError('model_unavailable', "Codex", "gpt-6-astra").message


def test_truncated_cli_omits_limit_reference():
    h = ModelError('truncated', "Codex").message
    assert "uříznutá" in h and "nastaveni.yaml" not in h


def test_truncated_api_references_limit():
    assert "nastaveni.yaml" in ModelError('truncated', "OpenAI").message


def test_cli_timeout():
    assert "Claude Code neodpověděla včas" in ModelError('timeout', "Claude Code").message


def test_redact_keys_is_public():
    from refiner.models.errors import redact_keys

    assert "sk-abc123" not in redact_keys("boom sk-abc123")

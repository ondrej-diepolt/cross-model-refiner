from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from pydantic import BaseModel

from refiner.data import Spotreba as TokenUsage, VystupNalezitosti as RequirementsOutput
from refiner.konfigurace import NastaveniClaude as ClaudeSettings, NastaveniGpt as GptSettings, NastaveniModelu as ModelSettings
from refiner.models.errors import ModelError
from refiner.models.claude import ClaudeModel


def settings(fallback: bool = True) -> ModelSettings:
    return ModelSettings(
        claude=ClaudeSettings(model="claude-opus-5-5", effort="high", effort_extrakce="low",
                               max_tokens_text=64000, max_tokens_json=16000, fallback=fallback),
        gpt=GptSettings(model="gpt-x", effort="high", max_output_tokens=1000),
        max_retries=2, timeout_s=30.0)


def message(stop_reason="end_turn", parsed=None, blocks=("{}",), category=None,
           usage=(100, 50, 30, 20)):
    return SimpleNamespace(
        stop_reason=stop_reason, parsed_output=parsed,
        stop_details=SimpleNamespace(category=category) if category else None,
        content=[SimpleNamespace(type="text", text=t) for t in blocks],
        usage=SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1],
                              cache_read_input_tokens=usage[2],
                              cache_creation_input_tokens=usage[3] if len(usage) > 3 else None))


class FakeClient:
    """Emulate beta.messages.stream; both json() and text() stream, never parse."""

    def __init__(self, response=None, exception=None, read_exception=None):
        self.last_kwargs = None
        self.stream_calls = 0
        self._response = response
        self._exception = exception
        self._read_exception = read_exception
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kw):
        self.last_kwargs = kw
        self.stream_calls += 1
        response = self._response
        exception = self._exception
        while_reading = self._read_exception

        def get_final_message():
            # The SDK parses structured output at content_block_stop, while reading the stream.
            if while_reading:
                raise while_reading
            return response

        class Context:
            def __enter__(self_):
                if exception:
                    raise exception
                return SimpleNamespace(get_final_message=get_final_message)

            def __exit__(self_, *a):
                return False

        return Context()


def test_json_sends_cache_effort_and_fallback():
    client = FakeClient(message(parsed=RequirementsOutput(nalezitosti=[])))
    m = ClaudeModel(settings(), client)
    m.json("INSTR", "ZADANI", RequirementsOutput, step="nalezitosti", effort="medium")
    kw = client.last_kwargs
    assert kw["model"] == "claude-opus-5-5"
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kw["system"][0]["text"] == "INSTR"
    assert kw["messages"] == [{"role": "user", "content": "ZADANI"}]
    assert kw["output_config"]["effort"] == "medium"
    assert kw["output_format"] is RequirementsOutput
    assert kw["max_tokens"] == 16000
    assert kw["fallbacks"] == "default"
    assert kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert "thinking" not in kw
    assert m.name == "claude-opus-5-5"


def test_json_streams():
    """Thinking tokens count toward max_tokens; the SDK rejects long non-streaming calls."""
    client = FakeClient(message(parsed=RequirementsOutput(nalezitosti=[])))
    out = ClaudeModel(settings(), client).json("I", "Z", RequirementsOutput, step="k")
    assert out == RequirementsOutput(nalezitosti=[])
    assert client.stream_calls == 1
    assert not hasattr(client.beta.messages, "parse")


def test_json_default_effort_from_settings():
    client = FakeClient(message(parsed=RequirementsOutput(nalezitosti=[])))
    ClaudeModel(settings(), client).json("I", "Z", RequirementsOutput, step="k")
    assert client.last_kwargs["output_config"]["effort"] == "high"


def test_json_without_fallback_when_disabled():
    client = FakeClient(message(parsed=RequirementsOutput(nalezitosti=[])))
    ClaudeModel(settings(fallback=False), client).json("I", "Z", RequirementsOutput, step="k")
    assert "fallbacks" not in client.last_kwargs
    assert "betas" not in client.last_kwargs


def test_text_streams_and_combines_blocks():
    client = FakeClient(message(blocks=("Ahoj ", "světe")))
    out = ClaudeModel(settings(), client).text("I", "Z", step="navrh")
    assert out == "Ahoj světe"
    assert client.last_kwargs["max_tokens"] == 64000
    assert "output_format" not in client.last_kwargs
    assert client.last_kwargs["fallbacks"] == "default"


def test_text_skips_non_text_blocks():
    msg = message(blocks=("A",))
    msg.content.insert(0, SimpleNamespace(type="thinking", thinking="x"))
    assert ClaudeModel(settings(), FakeClient(msg)).text("I", "Z", step="k") == "A"


def test_truncation():
    m = ClaudeModel(settings(), FakeClient(message(stop_reason="max_tokens")))
    with pytest.raises(ModelError) as e:
        m.json("I", "Z", RequirementsOutput, step="k")
    assert e.value.kind == 'truncated'
    with pytest.raises(ModelError) as e:
        m.text("I", "Z", step="k")
    assert e.value.kind == 'truncated'


def test_refusal_with_category():
    m = ClaudeModel(settings(), FakeClient(message(stop_reason="refusal", category="cyber")))
    with pytest.raises(ModelError) as e:
        m.json("I", "Z", RequirementsOutput, step="k")
    assert e.value.kind == 'refused' and e.value.detail == "cyber"
    assert e.value.service == "Anthropic"


def test_missing_parsed_output_is_invalid_with_raw_text():
    m = ClaudeModel(settings(), FakeClient(message(parsed=None, blocks=("nejson",))))
    with pytest.raises(ModelError) as e:
        m.json("I", "Z", RequirementsOutput, step="k")
    assert e.value.kind == 'invalid_output' and e.value.raw_response == "nejson"


def test_sdk_validation_error_is_invalid_output():
    class S(BaseModel):
        a: int

    try:
        S.model_validate({"a": "x"})
    except Exception as exc:
        exception = exc
    m = ClaudeModel(settings(), FakeClient(exception=exception))
    with pytest.raises(ModelError) as e:
        m.json("I", "Z", RequirementsOutput, step="k")
    assert e.value.kind == 'invalid_output'


def test_sdk_exception_is_converted():
    response = httpx2.Response(429, request=httpx2.Request("POST", "https://x"))
    exc = anthropic.RateLimitError("limit", response=response, body=None)
    m = ClaudeModel(settings(), FakeClient(exception=exc))
    with pytest.raises(ModelError) as e:
        m.json("I", "Z", RequirementsOutput, step="k")
    assert e.value.kind == 'overloaded'
    with pytest.raises(ModelError) as e:
        m.text("I", "Z", step="k")
    assert e.value.kind == 'overloaded'


def test_usage():
    client = FakeClient(message(parsed=RequirementsOutput(nalezitosti=[])))
    m = ClaudeModel(settings(), client)
    m.json("I", "Z", RequirementsOutput, step="nalezitosti")
    assert m.take_usage() == [TokenUsage(krok="nalezitosti", model="claude-opus-5-5",
                                              vstup=100, vystup=50, cache_cteni=30, cache_zapis=20)]
    assert m.take_usage() == []


def test_usage_without_cache():
    client = FakeClient(message(blocks=("a",), usage=(10, 5, None, None)))
    m = ClaudeModel(settings(), client)
    m.text("I", "Z", step="t")
    s = m.take_usage()[0]
    assert s.cache_cteni == 0 and s.cache_zapis == 0


def test_missing_key_is_authentication_error():
    with pytest.raises(ModelError) as e:
        ClaudeModel(settings())
    assert e.value.kind == 'authentication'


def test_default_client_with_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    m = ClaudeModel(settings())
    assert m.name == "claude-opus-5-5"


def test_truncated_parsed_json_keeps_raw_text():
    try:
        RequirementsOutput.model_validate_json('{"nalezitosti": [')
    except Exception as exc:
        exception = exc
    m = ClaudeModel(settings(), FakeClient(read_exception=exception))
    with pytest.raises(ModelError) as e:
        m.json("I", "Z", RequirementsOutput, step="k")
    assert e.value.kind == 'truncated' and e.value.raw_response == '{"nalezitosti": ['

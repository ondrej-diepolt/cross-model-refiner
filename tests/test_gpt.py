from types import SimpleNamespace

import httpx2
import openai
import pytest

from refiner.data import Hodnoceni as Evaluation, Spotreba as TokenUsage
from refiner.configuration import ClaudeSettings, GptSettings, ModelSettings
from refiner.models.errors import ModelError
from refiner.models.gpt import GptModel


def settings() -> ModelSettings:
    return ModelSettings(
        claude=ClaudeSettings(model="c", effort="high", extraction_effort="low",
                               max_tokens_text=1, max_tokens_json=1, fallback=True),
        gpt=GptSettings(model="gpt-x", effort="high", max_output_tokens=5000),
        max_retries=2, timeout_s=30.0)


EVALUATION = Evaluation(kriteria=[], vymyslena_fakta=[], tvrzeni_k_overeni=[], navrhy=[],
                      celkovy_komentar="ok")


def response(parsed=None, status="completed", reason=None, output=None, text="T",
            usage=(100, 50, 30)):
    return SimpleNamespace(
        status=status, output_parsed=parsed, output_text=text,
        incomplete_details=SimpleNamespace(reason=reason) if reason else None,
        output=output if output is not None else [
            SimpleNamespace(type="message", content=[SimpleNamespace(type="output_text", text=text)])],
        usage=SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1],
                              input_tokens_details=SimpleNamespace(cached_tokens=usage[2])))


class FakeClient:
    def __init__(self, response=None, exception=None):
        self.last_kwargs = None
        self.called = None
        self._response, self._exception = response, exception
        self.responses = SimpleNamespace(parse=self._f("parse"), create=self._f("create"))

    def _f(self, name):
        def f(**kw):
            self.last_kwargs, self.called = kw, name
            if self._exception:
                raise self._exception
            return self._response
        return f


def test_json_sends_reasoning_and_schema():
    client = FakeClient(response(parsed=EVALUATION))
    m = GptModel(settings(), client)
    out = m.json("INSTR", "ZADANI", Evaluation, step="hodnoceni", effort="low")
    kw = client.last_kwargs
    assert out is EVALUATION and client.called == "parse"
    assert kw["reasoning"] == {"effort": "high"}  # the protocol effort override is ignored
    assert kw["text_format"] is Evaluation
    assert kw["instructions"] == "INSTR" and kw["input"] == "ZADANI"
    assert kw["model"] == "gpt-x" and kw["max_output_tokens"] == 5000
    assert m.name == "gpt-x"


def test_text_uses_create_without_text_format():
    client = FakeClient(response(text="Ahoj"))
    assert GptModel(settings(), client).text("I", "Z", step="t") == "Ahoj"
    assert client.called == "create" and "text_format" not in client.last_kwargs


def test_incomplete_is_truncated():
    m = GptModel(settings(), FakeClient(response(status="incomplete", reason="max_output_tokens")))
    with pytest.raises(ModelError) as e:
        m.json("I", "Z", Evaluation, step="k")
    assert e.value.kind == 'truncated' and e.value.detail == "max_output_tokens"
    with pytest.raises(ModelError) as e:
        m.text("I", "Z", step="k")
    assert e.value.kind == 'truncated'


def test_refusal_is_refused():
    out = [SimpleNamespace(type="message",
                           content=[SimpleNamespace(type="refusal", refusal="Nemohu")])]
    m = GptModel(settings(), FakeClient(response(output=out)))
    with pytest.raises(ModelError) as e:
        m.json("I", "Z", Evaluation, step="k")
    assert e.value.kind == 'refused' and e.value.detail == "Nemohu"
    assert e.value.service == "OpenAI"


def test_missing_output_parsed_is_invalid():
    m = GptModel(settings(), FakeClient(response(parsed=None, text="blabla")))
    with pytest.raises(ModelError) as e:
        m.json("I", "Z", Evaluation, step="k")
    assert e.value.kind == 'invalid_output' and e.value.raw_response == "blabla"


def test_sdk_validation_error_is_invalid_output():
    try:
        Evaluation.model_validate_json("{}")
    except ValueError as exc:
        exception = exc
    m = GptModel(settings(), FakeClient(exception=exception))
    with pytest.raises(ModelError) as e:
        m.json("I", "Z", Evaluation, step="k")
    assert e.value.kind == 'invalid_output'


def test_sdk_exception_is_converted():
    exc = openai.APIConnectionError(request=httpx2.Request("POST", "https://x"))
    m = GptModel(settings(), FakeClient(exception=exc))
    with pytest.raises(ModelError) as e:
        m.json("I", "Z", Evaluation, step="k")
    assert e.value.kind == 'network'
    with pytest.raises(ModelError) as e:
        m.text("I", "Z", step="k")
    assert e.value.kind == 'network'


def test_usage_with_cached_tokens():
    m = GptModel(settings(), FakeClient(response(parsed=EVALUATION)))
    m.json("I", "Z", Evaluation, step="hodnoceni")
    assert m.take_usage() == [TokenUsage(krok="hodnoceni", model="gpt-x",
                                              vstup=100, vystup=50, cache_cteni=30)]
    assert m.take_usage() == []


def test_missing_key_is_authentication_error():
    with pytest.raises(ModelError) as e:
        GptModel(settings())
    assert e.value.kind == 'authentication'


def test_default_client_with_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    assert GptModel(settings()).name == "gpt-x"


def test_truncated_parsed_json_keeps_raw_text():
    try:
        Evaluation.model_validate_json('{"kriteria": [')
    except Exception as exc:
        exception = exc
    m = GptModel(settings(), FakeClient(exception=exception))
    with pytest.raises(ModelError) as e:
        m.json("I", "Z", Evaluation, step="k")
    assert e.value.kind == 'truncated' and e.value.raw_response == '{"kriteria": ['

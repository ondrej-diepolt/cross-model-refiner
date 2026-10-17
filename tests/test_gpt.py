from types import SimpleNamespace

import httpx2
import openai
import pytest

from refiner.data import Hodnoceni, Spotreba
from refiner.konfigurace import NastaveniClaude, NastaveniGpt, NastaveniModelu
from refiner.modely.chyby import ChybaModelu
from refiner.modely.gpt import GptModel


def nastaveni() -> NastaveniModelu:
    return NastaveniModelu(
        claude=NastaveniClaude(model="c", effort="high", effort_extrakce="low",
                               max_tokens_text=1, max_tokens_json=1, fallback=True),
        gpt=NastaveniGpt(model="gpt-x", effort="high", max_output_tokens=5000),
        max_retries=2, timeout_s=30.0)


HODNOCENI = Hodnoceni(kriteria=[], vymyslena_fakta=[], tvrzeni_k_overeni=[], navrhy=[],
                      celkovy_komentar="ok")


def odpoved(parsed=None, status="completed", duvod=None, output=None, text="T",
            usage=(100, 50, 30)):
    return SimpleNamespace(
        status=status, output_parsed=parsed, output_text=text,
        incomplete_details=SimpleNamespace(reason=duvod) if duvod else None,
        output=output if output is not None else [
            SimpleNamespace(type="message", content=[SimpleNamespace(type="output_text", text=text)])],
        usage=SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1],
                              input_tokens_details=SimpleNamespace(cached_tokens=usage[2])))


class FalesnyKlient:
    def __init__(self, odp=None, vyjimka=None):
        self.posledni_kwargs = None
        self.volano = None
        self._odp, self._vyjimka = odp, vyjimka
        self.responses = SimpleNamespace(parse=self._f("parse"), create=self._f("create"))

    def _f(self, jmeno):
        def f(**kw):
            self.posledni_kwargs, self.volano = kw, jmeno
            if self._vyjimka:
                raise self._vyjimka
            return self._odp
        return f


def test_json_posle_reasoning_a_schema():
    klient = FalesnyKlient(odpoved(parsed=HODNOCENI))
    m = GptModel(nastaveni(), klient)
    out = m.json("INSTR", "ZADANI", Hodnoceni, krok="hodnoceni", effort="low")
    kw = klient.posledni_kwargs
    assert out is HODNOCENI and klient.volano == "parse"
    assert kw["reasoning"] == {"effort": "high"}  # effort z protokolu se ignoruje
    assert kw["text_format"] is Hodnoceni
    assert kw["instructions"] == "INSTR" and kw["input"] == "ZADANI"
    assert kw["model"] == "gpt-x" and kw["max_output_tokens"] == 5000
    assert m.nazev == "gpt-x"


def test_text_pouzije_create_bez_text_format():
    klient = FalesnyKlient(odpoved(text="Ahoj"))
    assert GptModel(nastaveni(), klient).text("I", "Z", krok="t") == "Ahoj"
    assert klient.volano == "create" and "text_format" not in klient.posledni_kwargs


def test_incomplete_je_uriznuto():
    m = GptModel(nastaveni(), FalesnyKlient(odpoved(status="incomplete", duvod="max_output_tokens")))
    with pytest.raises(ChybaModelu) as e:
        m.json("I", "Z", Hodnoceni, krok="k")
    assert e.value.druh == "uriznuto" and e.value.detail == "max_output_tokens"
    with pytest.raises(ChybaModelu) as e:
        m.text("I", "Z", krok="k")
    assert e.value.druh == "uriznuto"


def test_refusal_je_odmitnuti():
    out = [SimpleNamespace(type="message",
                           content=[SimpleNamespace(type="refusal", refusal="Nemohu")])]
    m = GptModel(nastaveni(), FalesnyKlient(odpoved(output=out)))
    with pytest.raises(ChybaModelu) as e:
        m.json("I", "Z", Hodnoceni, krok="k")
    assert e.value.druh == "odmitnuti" and e.value.detail == "Nemohu"
    assert e.value.sluzba == "OpenAI"


def test_output_parsed_none_je_nevalidni():
    m = GptModel(nastaveni(), FalesnyKlient(odpoved(parsed=None, text="blabla")))
    with pytest.raises(ChybaModelu) as e:
        m.json("I", "Z", Hodnoceni, krok="k")
    assert e.value.druh == "nevalidni_vystup" and e.value.surova_odpoved == "blabla"


def test_validacni_chyba_sdk_je_nevalidni():
    try:
        Hodnoceni.model_validate_json("{")
    except ValueError as exc:
        vyjimka = exc
    m = GptModel(nastaveni(), FalesnyKlient(vyjimka=vyjimka))
    with pytest.raises(ChybaModelu) as e:
        m.json("I", "Z", Hodnoceni, krok="k")
    assert e.value.druh == "nevalidni_vystup"


def test_vyjimka_sdk_prevedena():
    exc = openai.APIConnectionError(request=httpx2.Request("POST", "https://x"))
    m = GptModel(nastaveni(), FalesnyKlient(vyjimka=exc))
    with pytest.raises(ChybaModelu) as e:
        m.json("I", "Z", Hodnoceni, krok="k")
    assert e.value.druh == "sit"
    with pytest.raises(ChybaModelu) as e:
        m.text("I", "Z", krok="k")
    assert e.value.druh == "sit"


def test_spotreba_s_cached_tokens():
    m = GptModel(nastaveni(), FalesnyKlient(odpoved(parsed=HODNOCENI)))
    m.json("I", "Z", Hodnoceni, krok="hodnoceni")
    assert m.vyzvedni_spotrebu() == [Spotreba(krok="hodnoceni", model="gpt-x",
                                              vstup=100, vystup=50, cache_cteni=30)]
    assert m.vyzvedni_spotrebu() == []


def test_chybejici_klic_je_chyba_klic():
    with pytest.raises(ChybaModelu) as e:
        GptModel(nastaveni())
    assert e.value.druh == "klic"


def test_vychozi_klient_s_klicem(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    assert GptModel(nastaveni()).nazev == "gpt-x"

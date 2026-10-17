from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from pydantic import BaseModel

from refiner.data import Spotreba, VystupNalezitosti
from refiner.konfigurace import NastaveniClaude, NastaveniGpt, NastaveniModelu
from refiner.modely.chyby import ChybaModelu
from refiner.modely.claude import ClaudeModel


def nastaveni(fallback: bool = True) -> NastaveniModelu:
    return NastaveniModelu(
        claude=NastaveniClaude(model="claude-opus-5-5", effort="high", effort_extrakce="low",
                               max_tokens_text=64000, max_tokens_json=16000, fallback=fallback),
        gpt=NastaveniGpt(model="gpt-x", effort="high", max_output_tokens=1000),
        max_retries=2, timeout_s=30.0)


def zprava(stop_reason="end_turn", parsed=None, bloky=("{}",), category=None,
           usage=(100, 50, 30, 20)):
    return SimpleNamespace(
        stop_reason=stop_reason, parsed_output=parsed,
        stop_details=SimpleNamespace(category=category) if category else None,
        content=[SimpleNamespace(type="text", text=t) for t in bloky],
        usage=SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1],
                              cache_read_input_tokens=usage[2],
                              cache_creation_input_tokens=usage[3] if len(usage) > 3 else None))


class FalesnyKlient:
    """Napodobí beta.messages.stream; json() i text() streamují (parse se nesmí volat)."""

    def __init__(self, odpoved=None, vyjimka=None, vyjimka_pri_cteni=None):
        self.posledni_kwargs = None
        self.volani_stream = 0
        self._odpoved = odpoved
        self._vyjimka = vyjimka
        self._vyjimka_pri_cteni = vyjimka_pri_cteni
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kw):
        self.posledni_kwargs = kw
        self.volani_stream += 1
        odpoved = self._odpoved
        vyjimka = self._vyjimka
        pri_cteni = self._vyjimka_pri_cteni

        def get_final_message():
            # SDK parsuje strukturovaný výstup při content_block_stop, tedy během čtení proudu.
            if pri_cteni:
                raise pri_cteni
            return odpoved

        class Kontext:
            def __enter__(self_):
                if vyjimka:
                    raise vyjimka
                return SimpleNamespace(get_final_message=get_final_message)

            def __exit__(self_, *a):
                return False

        return Kontext()


def test_json_posle_cache_effort_a_fallback():
    klient = FalesnyKlient(zprava(parsed=VystupNalezitosti(nalezitosti=[])))
    m = ClaudeModel(nastaveni(), klient)
    m.json("INSTR", "ZADANI", VystupNalezitosti, krok="nalezitosti", effort="medium")
    kw = klient.posledni_kwargs
    assert kw["model"] == "claude-opus-5-5"
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kw["system"][0]["text"] == "INSTR"
    assert kw["messages"] == [{"role": "user", "content": "ZADANI"}]
    assert kw["output_config"]["effort"] == "medium"
    assert kw["output_format"] is VystupNalezitosti
    assert kw["max_tokens"] == 16000
    assert kw["fallbacks"] == "default"
    assert kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert "thinking" not in kw
    assert m.nazev == "claude-opus-5-5"


def test_json_streamuje():
    """Thinking tokeny se počítají do max_tokens; dlouhé volání bez streamu by SDK odmítlo."""
    klient = FalesnyKlient(zprava(parsed=VystupNalezitosti(nalezitosti=[])))
    out = ClaudeModel(nastaveni(), klient).json("I", "Z", VystupNalezitosti, krok="k")
    assert out == VystupNalezitosti(nalezitosti=[])
    assert klient.volani_stream == 1
    assert not hasattr(klient.beta.messages, "parse")


def test_json_vychozi_effort_z_nastaveni():
    klient = FalesnyKlient(zprava(parsed=VystupNalezitosti(nalezitosti=[])))
    ClaudeModel(nastaveni(), klient).json("I", "Z", VystupNalezitosti, krok="k")
    assert klient.posledni_kwargs["output_config"]["effort"] == "high"


def test_json_bez_fallbacku_kdyz_vypnuto():
    klient = FalesnyKlient(zprava(parsed=VystupNalezitosti(nalezitosti=[])))
    ClaudeModel(nastaveni(fallback=False), klient).json("I", "Z", VystupNalezitosti, krok="k")
    assert "fallbacks" not in klient.posledni_kwargs
    assert "betas" not in klient.posledni_kwargs


def test_text_streamuje_a_spoji_bloky():
    klient = FalesnyKlient(zprava(bloky=("Ahoj ", "světe")))
    out = ClaudeModel(nastaveni(), klient).text("I", "Z", krok="navrh")
    assert out == "Ahoj světe"
    assert klient.posledni_kwargs["max_tokens"] == 64000
    assert "output_format" not in klient.posledni_kwargs
    assert klient.posledni_kwargs["fallbacks"] == "default"


def test_text_preskoci_ne_textove_bloky():
    msg = zprava(bloky=("A",))
    msg.content.insert(0, SimpleNamespace(type="thinking", thinking="x"))
    assert ClaudeModel(nastaveni(), FalesnyKlient(msg)).text("I", "Z", krok="k") == "A"


def test_uriznuti():
    m = ClaudeModel(nastaveni(), FalesnyKlient(zprava(stop_reason="max_tokens")))
    with pytest.raises(ChybaModelu) as e:
        m.json("I", "Z", VystupNalezitosti, krok="k")
    assert e.value.druh == "uriznuto"
    with pytest.raises(ChybaModelu) as e:
        m.text("I", "Z", krok="k")
    assert e.value.druh == "uriznuto"


def test_odmitnuti_s_kategorii():
    m = ClaudeModel(nastaveni(), FalesnyKlient(zprava(stop_reason="refusal", category="cyber")))
    with pytest.raises(ChybaModelu) as e:
        m.json("I", "Z", VystupNalezitosti, krok="k")
    assert e.value.druh == "odmitnuti" and e.value.detail == "cyber"
    assert e.value.sluzba == "Anthropic"


def test_parsed_output_none_je_nevalidni_se_surovym_textem():
    m = ClaudeModel(nastaveni(), FalesnyKlient(zprava(parsed=None, bloky=("nejson",))))
    with pytest.raises(ChybaModelu) as e:
        m.json("I", "Z", VystupNalezitosti, krok="k")
    assert e.value.druh == "nevalidni_vystup" and e.value.surova_odpoved == "nejson"


def test_validacni_chyba_sdk_je_nevalidni():
    class S(BaseModel):
        a: int

    try:
        S.model_validate({"a": "x"})
    except Exception as exc:
        vyjimka = exc
    m = ClaudeModel(nastaveni(), FalesnyKlient(vyjimka=vyjimka))
    with pytest.raises(ChybaModelu) as e:
        m.json("I", "Z", VystupNalezitosti, krok="k")
    assert e.value.druh == "nevalidni_vystup"


def test_vyjimka_sdk_prevedena():
    odpoved = httpx2.Response(429, request=httpx2.Request("POST", "https://x"))
    exc = anthropic.RateLimitError("limit", response=odpoved, body=None)
    m = ClaudeModel(nastaveni(), FalesnyKlient(vyjimka=exc))
    with pytest.raises(ChybaModelu) as e:
        m.json("I", "Z", VystupNalezitosti, krok="k")
    assert e.value.druh == "pretizeni"
    with pytest.raises(ChybaModelu) as e:
        m.text("I", "Z", krok="k")
    assert e.value.druh == "pretizeni"


def test_spotreba():
    klient = FalesnyKlient(zprava(parsed=VystupNalezitosti(nalezitosti=[])))
    m = ClaudeModel(nastaveni(), klient)
    m.json("I", "Z", VystupNalezitosti, krok="nalezitosti")
    assert m.vyzvedni_spotrebu() == [Spotreba(krok="nalezitosti", model="claude-opus-5-5",
                                              vstup=100, vystup=50, cache_cteni=30, cache_zapis=20)]
    assert m.vyzvedni_spotrebu() == []


def test_spotreba_bez_cache():
    klient = FalesnyKlient(zprava(bloky=("a",), usage=(10, 5, None, None)))
    m = ClaudeModel(nastaveni(), klient)
    m.text("I", "Z", krok="t")
    s = m.vyzvedni_spotrebu()[0]
    assert s.cache_cteni == 0 and s.cache_zapis == 0


def test_chybejici_klic_je_chyba_klic():
    with pytest.raises(ChybaModelu) as e:
        ClaudeModel(nastaveni())
    assert e.value.druh == "klic"


def test_vychozi_klient_s_klicem(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    m = ClaudeModel(nastaveni())
    assert m.nazev == "claude-opus-5-5"


def test_uriznuty_json_z_parse_je_uriznuto_se_surovym_textem():
    try:
        VystupNalezitosti.model_validate_json('{"nalezitosti": [')
    except Exception as exc:
        vyjimka = exc
    m = ClaudeModel(nastaveni(), FalesnyKlient(vyjimka_pri_cteni=vyjimka))
    with pytest.raises(ChybaModelu) as e:
        m.json("I", "Z", VystupNalezitosti, krok="k")
    assert e.value.druh == "uriznuto" and e.value.surova_odpoved == '{"nalezitosti": ['

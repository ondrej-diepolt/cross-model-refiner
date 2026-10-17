import anthropic
import httpx2
import openai
import pytest

from refiner.modely.chyby import ChybaModelu, prevod_vyjimky

REQ = httpx2.Request("POST", "https://api.example/v1")


def resp(code):
    return httpx2.Response(code, request=REQ)


@pytest.mark.parametrize("exc,sluzba,druh", [
    (anthropic.AuthenticationError("x", response=resp(401), body=None), "Anthropic", "klic"),
    (anthropic.RateLimitError("x", response=resp(429), body=None), "Anthropic", "pretizeni"),
    (anthropic.InternalServerError("x", response=resp(529), body=None), "Anthropic", "pretizeni"),
    (anthropic.APITimeoutError(request=REQ), "Anthropic", "timeout"),
    (anthropic.APIConnectionError(request=REQ), "Anthropic", "sit"),
    (anthropic.BadRequestError("Your credit balance is too low", response=resp(400), body=None), "Anthropic", "kredit"),
    (openai.AuthenticationError("x", response=resp(401), body=None), "OpenAI", "klic"),
    (openai.RateLimitError("x", response=resp(429), body={"code": "insufficient_quota"}), "OpenAI", "kredit"),
    (openai.RateLimitError("x", response=resp(429), body={"code": "rate_limit_exceeded"}), "OpenAI", "pretizeni"),
    (openai.APITimeoutError(request=REQ), "OpenAI", "timeout"),
    (ValueError("??"), "OpenAI", "jina"),
])
def test_prevod_vyjimky(exc, sluzba, druh):
    assert prevod_vyjimky(exc, sluzba).druh == druh


def test_hlaska_klic_jmenuje_promennou():
    assert "OPENAI_API_KEY" in ChybaModelu("klic", "OpenAI").hlaska


def test_hlaska_odmitnuti_s_kategorii():
    assert "cyber" in ChybaModelu("odmitnuti", "Anthropic", "cyber").hlaska


def test_chyba_modelu_projde_beze_zmeny():
    chyba = ChybaModelu("sit", "OpenAI")
    assert prevod_vyjimky(chyba, "OpenAI") is chyba

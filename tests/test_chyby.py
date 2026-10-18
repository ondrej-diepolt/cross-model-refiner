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


def test_hlaska_uriznuto_rika_co_zvysit():
    claude = ChybaModelu("uriznuto", "Anthropic").hlaska
    gpt = ChybaModelu("uriznuto", "OpenAI").hlaska
    assert "uříznutá" in claude and "nastaveni.yaml" in claude and "pokracovat.bat" in claude
    assert "max_tokens_json" in claude and "max_output_tokens" not in claude
    assert "max_output_tokens" in gpt and "max_tokens_json" not in gpt
    assert "ani po opakování" not in claude


def test_hlaska_odmitnuti_s_kategorii():
    assert "cyber" in ChybaModelu("odmitnuti", "Anthropic", "cyber").hlaska


def test_chyba_modelu_projde_beze_zmeny():
    chyba = ChybaModelu("sit", "OpenAI")
    assert prevod_vyjimky(chyba, "OpenAI") is chyba


def test_detail_neobsahuje_klic():
    exc = openai.AuthenticationError(
        "Incorrect API key provided: sk-proj-****abcd and sk-ant-api03-XYZ_12",
        response=resp(401), body=None)
    e = prevod_vyjimky(exc, "OpenAI")
    assert "sk-proj" not in e.detail and "abcd" not in e.detail and "XYZ" not in e.detail
    assert "sk-" in e.detail


@pytest.mark.parametrize("sluzba,prikaz", [("Claude Code", "claude"), ("Codex", "codex")])
def test_nenainstalovano_jmenuje_prikaz(sluzba, prikaz):
    h = ChybaModelu("nenainstalovano", sluzba).hlaska
    assert f"příkaz {prikaz} nebyl nalezen" in h and "modely.rezim na api" in h


def test_neprihlasen_codex_rika_jak_se_prihlasit():
    assert "codex login" in ChybaModelu("neprihlasen", "Codex").hlaska


def test_neprihlasen_claude_rika_jak_se_prihlasit():
    assert "/login" in ChybaModelu("neprihlasen", "Claude Code").hlaska


def test_limit_obsahuje_text_nastroje():
    h = ChybaModelu("limit_predplatneho", "Claude Code", "You've hit your session limit · resets 3:45pm").hlaska
    assert "resets 3:45pm" in h and "pokracovat.bat" in h


def test_model_nedostupny_jmenuje_model():
    assert "gpt-6-astra" in ChybaModelu("model_nedostupny", "Codex", "gpt-6-astra").hlaska


def test_uriznuto_nastroje_bez_odkazu_na_limit():
    h = ChybaModelu("uriznuto", "Codex").hlaska
    assert "uříznutá" in h and "nastaveni.yaml" not in h


def test_uriznuto_api_odkazuje_na_limit():
    assert "nastaveni.yaml" in ChybaModelu("uriznuto", "OpenAI").hlaska


def test_timeout_nastroje():
    assert "Claude Code neodpověděla včas" in ChybaModelu("timeout", "Claude Code").hlaska


def test_skryj_klice_je_verejna():
    from refiner.modely.chyby import skryj_klice

    assert "sk-abc123" not in skryj_klice("boom sk-abc123")

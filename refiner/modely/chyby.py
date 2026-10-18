import re
from typing import Literal

import pydantic

import anthropic
import openai

DruhChyby = Literal["klic", "kredit", "pretizeni", "sit", "timeout",
                    "nevalidni_vystup", "uriznuto", "odmitnuti", "jina",
                    "nenainstalovano", "neprihlasen", "limit_predplatneho", "model_nedostupny"]
Sluzba = Literal["Anthropic", "OpenAI", "Claude Code", "Codex"]
# Služby poskytované přes CLI nástroje (režim predplatne).
NASTROJE: frozenset[Sluzba] = frozenset({"Claude Code", "Codex"})

HLASKY: dict[DruhChyby, str] = {
    "klic": "Klíč {klic} v souboru .env chybí nebo je neplatný.",
    "kredit": "Došel kredit u {sluzba}. Dobijte kredit a spusťte pokracovat.bat.",
    "pretizeni": "Služba {sluzba} je přetížená, zkuste to za pár minut a spusťte pokracovat.bat.",
    "sit": "Nepodařilo se spojit se službou {sluzba}. Zkontrolujte připojení a spusťte pokracovat.bat.",
    "timeout": "Služba {sluzba} neodpověděla včas. Zkuste to znovu přes pokracovat.bat.",
    "nevalidni_vystup": "Model {sluzba} vrátil neplatnou odpověď ani po opravě. Surová odpověď je ve složce data/.",
    "uriznuto": ("Odpověď modelu {sluzba} byla uříznutá (příliš dlouhá). Zvyšte v souboru "
                 "nastaveni.yaml limit {limit} a spusťte pokracovat.bat."),
    "odmitnuti": "Model {sluzba} úlohu odmítl (kategorie: {detail}).",
    "jina": "Neočekávaná chyba služby {sluzba}: {detail}",
    "nenainstalovano": ("Nástroj {sluzba} není nainstalovaný (příkaz {prikaz} nebyl nalezen). "
                        "Nainstalujte ho podle README, nebo v nastaveni.yaml přepněte modely.rezim na api."),
    "neprihlasen": ("Nástroj {sluzba} není přihlášený předplatným. Přihlaste se příkazem {prihlaseni} "
                    "a spusťte nástroj znovu (přerušený běh dokončí pokracovat.bat)."),
    "limit_predplatneho": ("Vyčerpali jste limit předplatného u {sluzba} ({detail}). "
                           "Až se limit obnoví, spusťte pokracovat.bat."),
    "model_nedostupny": ("Model {detail} není s vaším předplatným {sluzba} dostupný. "
                         "Změňte ho v nastaveni.yaml v oddílu modely.predplatne."),
}
# U nástrojů nejde délku odpovědi v nastavení změnit, proto bez odkazu na limit.
_HLASKY_NASTROJU: dict[DruhChyby, str] = {
    "uriznuto": "Odpověď modelu {sluzba} byla uříznutá (příliš dlouhá).",
}

_KLICE = {"Anthropic": "ANTHROPIC_API_KEY", "OpenAI": "OPENAI_API_KEY"}
# Položky nastaveni.yaml omezující délku odpovědi (pokračující běh je bere z repozitáře).
_PRIKAZY = {"Claude Code": "claude", "Codex": "codex"}
_PRIHLASENI = {"Claude Code": "claude (v něm /login)", "Codex": "codex login"}
_LIMITY = {"Anthropic": "max_tokens_json (u textu max_tokens_text) v oddílu modely.claude",
           "OpenAI": "max_output_tokens v oddílu modely.gpt"}


class ChybaModelu(Exception):
    def __init__(self, druh: DruhChyby, sluzba: Sluzba, detail: str = "",
                 surova_odpoved: str | None = None):
        self.druh = druh
        self.sluzba = sluzba
        self.detail = detail
        self.surova_odpoved = surova_odpoved
        sablona = _HLASKY_NASTROJU.get(druh) if sluzba in NASTROJE else None
        self.hlaska = (sablona or HLASKY[druh]).format(
            klic=_KLICE.get(sluzba, ""), sluzba=sluzba, detail=detail, limit=_LIMITY.get(sluzba, ""),
            prikaz=_PRIKAZY.get(sluzba, ""), prihlaseni=_PRIHLASENI.get(sluzba, ""))
        super().__init__(self.hlaska)


def _kod_openai(exc: Exception) -> str | None:
    kod = getattr(exc, "code", None)
    if kod is None:
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            kod = body.get("code")
    return kod if isinstance(kod, str) else None


_KLIC_RE = re.compile(r"sk-[A-Za-z0-9_\-\*]+")


def skryj_klice(text: str) -> str:
    """Odstraní z textu výjimky řetězce podobné API klíči (i částečně maskované)."""
    return _KLIC_RE.sub("sk-***", text)


_skryj_klice = skryj_klice  # alias kvůli stávajícímu kódu


def chyba_parsovani(exc: Exception, sluzba: Sluzba) -> ChybaModelu:
    """Převede chybu parsování strukturované odpovědi z SDK.

    SDK validuje JSON dřív, než vrátí stop_reason/status, takže uříznutý JSON
    (pydantic json_invalid, "EOF while parsing") se tu rozpozná jako uříznuté.
    """
    err = {}
    if isinstance(exc, pydantic.ValidationError) and exc.errors():
        err = exc.errors()[0]
    surova = err.get("input") if err.get("type") == "json_invalid" else None
    if not isinstance(surova, str):
        surova = None
    if surova is not None and "EOF while parsing" in err.get("msg", ""):
        return ChybaModelu("uriznuto", sluzba, detail="EOF", surova_odpoved=surova)
    return ChybaModelu("nevalidni_vystup", sluzba, detail=skryj_klice(str(exc)),
                       surova_odpoved=surova)


def prevod_vyjimky(exc: Exception, sluzba: Sluzba) -> ChybaModelu:
    if isinstance(exc, ChybaModelu):
        return exc
    detail = skryj_klice(str(exc))
    knihovny = (anthropic, openai)
    # APITimeoutError je podtřída APIConnectionError – nejdřív timeout.
    if any(isinstance(exc, k.APITimeoutError) for k in knihovny):
        return ChybaModelu("timeout", sluzba, detail)
    if any(isinstance(exc, k.APIConnectionError) for k in knihovny):
        return ChybaModelu("sit", sluzba, detail)
    if any(isinstance(exc, k.AuthenticationError) for k in knihovny):
        return ChybaModelu("klic", sluzba, detail)
    if isinstance(exc, openai.RateLimitError):
        if _kod_openai(exc) == "insufficient_quota":
            return ChybaModelu("kredit", sluzba, detail)
        return ChybaModelu("pretizeni", sluzba, detail)
    if isinstance(exc, (anthropic.BadRequestError, anthropic.PermissionDeniedError)):
        if "credit balance" in detail.lower():
            return ChybaModelu("kredit", sluzba, detail)
        return ChybaModelu("jina", sluzba, detail)
    if isinstance(exc, anthropic.RateLimitError):
        return ChybaModelu("pretizeni", sluzba, detail)
    if isinstance(exc, (anthropic.InternalServerError, openai.InternalServerError)):
        return ChybaModelu("pretizeni", sluzba, detail)
    return ChybaModelu("jina", sluzba, detail)

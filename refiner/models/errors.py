import re
from typing import Literal

import pydantic

import anthropic
import openai

ErrorKind = Literal['authentication', 'credit', 'overloaded', 'network', 'timeout',
                    'invalid_output', 'truncated', 'refused', 'other',
                    'not_installed', 'not_authenticated', 'subscription_limit', 'model_unavailable']
Service = Literal["Anthropic", "OpenAI", "Claude Code", "Codex"]
# Services accessed through subscription CLI tools.
CLI_SERVICES: frozenset[Service] = frozenset({"Claude Code", "Codex"})

MESSAGES: dict[ErrorKind, str] = {
    'authentication': "Klíč {key} v souboru .env chybí nebo je neplatný.",
    'credit': "Došel kredit u {service}. Dobijte kredit a spusťte pokracovat.bat.",
    'overloaded': "Služba {service} je přetížená, zkuste to za pár minut a spusťte pokracovat.bat.",
    'network': "Nepodařilo se spojit se službou {service}. Zkontrolujte připojení a spusťte pokracovat.bat.",
    'timeout': "Služba {service} neodpověděla včas. Zkuste to znovu přes pokracovat.bat.",
    'invalid_output': "Model {service} vrátil neplatnou odpověď ani po opravě. Surová odpověď je ve složce data/.",
    'truncated': ("Odpověď modelu {service} byla uříznutá (příliš dlouhá). Zvyšte v souboru "
                 "nastaveni.yaml limit {limit} a spusťte pokracovat.bat."),
    'refused': "Model {service} úlohu odmítl (kategorie: {detail}).",
    'other': "Neočekávaná chyba služby {service}: {detail}",
    'not_installed': ("Nástroj {service} není nainstalovaný (příkaz {command} nebyl nalezen). "
                        "Nainstalujte ho podle README, nebo v nastaveni.yaml přepněte modely.rezim na api."),
    'not_authenticated': ("Nástroj {service} není přihlášený předplatným. Přihlaste se příkazem {login} "
                    "a spusťte nástroj znovu (přerušený běh dokončí pokracovat.bat)."),
    'subscription_limit': ("Vyčerpali jste limit předplatného u {service} ({detail}). "
                           "Až se limit obnoví, spusťte pokracovat.bat."),
    'model_unavailable': ("Model {detail} není s vaším předplatným {service} dostupný. "
                         "Změňte ho v nastaveni.yaml v oddílu modely.predplatne."),
}
# CLI response lengths are not configurable here, so omit limit instructions.
_CLI_MESSAGES: dict[ErrorKind, str] = {
    'truncated': "Odpověď modelu {service} byla uříznutá (příliš dlouhá).",
}

_KEYS = {"Anthropic": "ANTHROPIC_API_KEY", "OpenAI": "OPENAI_API_KEY"}
# Response-length settings in nastaveni.yaml (resumed runs use repository values).
_COMMANDS = {"Claude Code": "claude", "Codex": "codex"}
_LOGIN_COMMANDS = {"Claude Code": "claude (v něm /login)", "Codex": "codex login"}
_LIMITS = {"Anthropic": "max_tokens_json (u textu max_tokens_text) v oddílu modely.claude",
           "OpenAI": "max_output_tokens v oddílu modely.gpt"}


class ModelError(Exception):
    def __init__(self, kind: ErrorKind, service: Service, detail: str = "",
                 raw_response: str | None = None):
        self.kind = kind
        self.service = service
        self.detail = detail
        self.raw_response = raw_response
        template = _CLI_MESSAGES.get(kind) if service in CLI_SERVICES else None
        self.message = (template or MESSAGES[kind]).format(
            key=_KEYS.get(service, ""), service=service, detail=detail, limit=_LIMITS.get(service, ""),
            command=_COMMANDS.get(service, ""), login=_LOGIN_COMMANDS.get(service, ""))
        super().__init__(self.message)


def _openai_code(exc: Exception) -> str | None:
    code = getattr(exc, "code", None)
    if code is None:
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            code = body.get("code")
    return code if isinstance(code, str) else None


_KEY_RE = re.compile(r"sk-[A-Za-z0-9_\-\*]+")


def redact_keys(text: str) -> str:
    """Redact API-key-like strings from exception text, including partially masked keys."""
    return _KEY_RE.sub("sk-***", text)


def parsing_error(exc: Exception, service: Service) -> ModelError:
    """Convert an SDK structured-output parsing error.

    The SDK validates JSON before returning stop_reason/status. Recognize truncated
    JSON through pydantic json_invalid with "EOF while parsing".
    """
    err = {}
    if isinstance(exc, pydantic.ValidationError) and exc.errors():
        err = exc.errors()[0]
    raw = err.get("input") if err.get("type") == "json_invalid" else None
    if not isinstance(raw, str):
        raw = None
    if raw is not None and "EOF while parsing" in err.get("msg", ""):
        return ModelError('truncated', service, detail="EOF", raw_response=raw)
    return ModelError('invalid_output', service, detail=redact_keys(str(exc)),
                       raw_response=raw)


def convert_exception(exc: Exception, service: Service) -> ModelError:
    if isinstance(exc, ModelError):
        return exc
    detail = redact_keys(str(exc))
    libraries = (anthropic, openai)
    # APITimeoutError subclasses APIConnectionError; check timeouts first.
    if any(isinstance(exc, k.APITimeoutError) for k in libraries):
        return ModelError('timeout', service, detail)
    if any(isinstance(exc, k.APIConnectionError) for k in libraries):
        return ModelError('network', service, detail)
    if any(isinstance(exc, k.AuthenticationError) for k in libraries):
        return ModelError('authentication', service, detail)
    if isinstance(exc, openai.RateLimitError):
        if _openai_code(exc) == "insufficient_quota":
            return ModelError('credit', service, detail)
        return ModelError('overloaded', service, detail)
    if isinstance(exc, (anthropic.BadRequestError, anthropic.PermissionDeniedError)):
        if "credit balance" in detail.lower():
            return ModelError('credit', service, detail)
        return ModelError('other', service, detail)
    if isinstance(exc, anthropic.RateLimitError):
        return ModelError('overloaded', service, detail)
    if isinstance(exc, (anthropic.InternalServerError, openai.InternalServerError)):
        return ModelError('overloaded', service, detail)
    return ModelError('other', service, detail)

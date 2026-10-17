"""Klient Anthropic (Claude) implementující protokol Model."""
from __future__ import annotations

import json
import os
from typing import Any, TypeVar

import anthropic
import pydantic
from pydantic import BaseModel

from refiner.data import Spotreba
from refiner.konfigurace import NastaveniModelu
from refiner.modely.chyby import ChybaModelu, chyba_parsovani, prevod_vyjimky

T = TypeVar("T", bound=BaseModel)

_SLUZBA = "Anthropic"
_BETA_FALLBACK = "server-side-fallback-2026-07-01"


class ClaudeModel:
    def __init__(self, nastaveni: NastaveniModelu, klient: Any | None = None):
        self._n = nastaveni
        self.nazev = nastaveni.claude.model
        self._spotreba: list[Spotreba] = []
        if klient is None:
            # Anthropic() při chybějícím klíči nespadne hned, ale až u prvního volání.
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise ChybaModelu("klic", _SLUZBA)
            try:
                klient = anthropic.Anthropic(max_retries=nastaveni.max_retries,
                                             timeout=nastaveni.timeout_s)
            except Exception as exc:
                raise prevod_vyjimky(exc, _SLUZBA) from exc
        self._klient = klient

    def _spolecne(self, instrukce: str, zadani: str, effort: str | None) -> dict[str, Any]:
        n = self._n.claude
        kw: dict[str, Any] = {
            "model": n.model,
            "system": [{"type": "text", "text": instrukce,
                        "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": zadani}],
            "output_config": {"effort": effort or n.effort},
        }
        # Ověřeno v anthropic 1.15.0: beta.messages.parse i stream přijímají `betas`,
        # `fallbacks`, `output_config` i `output_format` přímo, extra_body netřeba.
        # `thinking` se neposílá (Opus 5.5 běží adaptivně).
        if n.fallback:
            kw["betas"] = [_BETA_FALLBACK]
            kw["fallbacks"] = "default"
        return kw

    @staticmethod
    def _text_zpravy(msg: Any) -> str:
        return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")

    def _zpracuj(self, msg: Any, krok: str) -> None:
        """Zapíše spotřebu (tokeny se platí i při chybě) a převede stop_reason na chybu."""
        u = msg.usage
        self._spotreba.append(Spotreba(
            krok=krok, model=self.nazev, vstup=u.input_tokens, vystup=u.output_tokens,
            cache_cteni=u.cache_read_input_tokens or 0,
            cache_zapis=getattr(u, "cache_creation_input_tokens", None) or 0))
        if msg.stop_reason == "refusal":
            kategorie = getattr(getattr(msg, "stop_details", None), "category", None)
            raise ChybaModelu("odmitnuti", _SLUZBA, detail=str(kategorie or "nespecifikováno"))
        if msg.stop_reason == "max_tokens":
            raise ChybaModelu("uriznuto", _SLUZBA)

    def json(self, instrukce: str, zadani: str, schema: type[T], *, krok: str,
             effort: str | None = None) -> T:
        kw = self._spolecne(instrukce, zadani, effort)
        try:
            # Stream i pro JSON: thinking tokeny se počítají do max_tokens, takže limit musí
            # být vysoký, a SDK nestreamované volání s vysokým max_tokens odmítá (dlouhé volání).
            # Ověřeno v anthropic 1.15.0: BetaMessageStream přijímá output_format a vyplní
            # parsed_output (parsuje při content_block_stop – chyby parsování vzniknou při čtení).
            with self._klient.beta.messages.stream(
                    **kw, max_tokens=self._n.claude.max_tokens_json, output_format=schema) as proud:
                msg = proud.get_final_message()
            self._zpracuj(msg, krok)
            if msg.parsed_output is None:
                raise ChybaModelu("nevalidni_vystup", _SLUZBA, detail="chybí parsed_output",
                                  surova_odpoved=self._text_zpravy(msg))
            return msg.parsed_output
        except ChybaModelu:
            raise
        except (pydantic.ValidationError, json.JSONDecodeError) as exc:
            raise chyba_parsovani(exc, _SLUZBA) from exc
        except Exception as exc:
            raise prevod_vyjimky(exc, _SLUZBA) from exc

    def text(self, instrukce: str, zadani: str, *, krok: str) -> str:
        kw = self._spolecne(instrukce, zadani, None)
        try:
            with self._klient.beta.messages.stream(
                    **kw, max_tokens=self._n.claude.max_tokens_text) as proud:
                msg = proud.get_final_message()
            self._zpracuj(msg, krok)
            return self._text_zpravy(msg)
        except ChybaModelu:
            raise
        except Exception as exc:
            raise prevod_vyjimky(exc, _SLUZBA) from exc

    def vyzvedni_spotrebu(self) -> list[Spotreba]:
        spotreba, self._spotreba = self._spotreba, []
        return spotreba

"""Klient OpenAI (GPT, Responses API) implementující protokol Model."""
from __future__ import annotations

import os
from typing import Any, TypeVar

import openai
from pydantic import BaseModel

from refiner.data import Spotreba
from refiner.konfigurace import NastaveniModelu
from refiner.modely.chyby import ChybaModelu, prevod_vyjimky

T = TypeVar("T", bound=BaseModel)

_SLUZBA = "OpenAI"


class GptModel:
    def __init__(self, nastaveni: NastaveniModelu, klient: Any | None = None):
        self._n = nastaveni
        self.nazev = nastaveni.gpt.model
        self._spotreba: list[Spotreba] = []
        if klient is None:
            if not os.environ.get("OPENAI_API_KEY"):
                raise ChybaModelu("klic", _SLUZBA)
            try:
                klient = openai.OpenAI(max_retries=nastaveni.max_retries,
                                       timeout=nastaveni.timeout_s)
            except Exception as exc:
                raise prevod_vyjimky(exc, _SLUZBA) from exc
        self._klient = klient

    def _spolecne(self, instrukce: str, zadani: str) -> dict[str, Any]:
        n = self._n.gpt
        # Ověřeno v openai 3.33.0: responses.parse i create přijímají všechny tyto
        # parametry přímo. Parametr `effort` z protokolu se ignoruje (platí n.effort).
        return {"model": n.model, "instructions": instrukce, "input": zadani,
                "reasoning": {"effort": n.effort}, "max_output_tokens": n.max_output_tokens}

    def _zpracuj(self, odp: Any, krok: str) -> None:
        u = odp.usage
        detaily = getattr(u, "input_tokens_details", None)
        self._spotreba.append(Spotreba(
            krok=krok, model=self.nazev, vstup=u.input_tokens, vystup=u.output_tokens,
            cache_cteni=(getattr(detaily, "cached_tokens", 0) or 0)))
        if odp.status == "incomplete":
            duvod = getattr(getattr(odp, "incomplete_details", None), "reason", None)
            raise ChybaModelu("uriznuto", _SLUZBA, detail=str(duvod or ""))
        for polozka in odp.output:
            for obsah in getattr(polozka, "content", None) or []:
                if getattr(obsah, "type", None) == "refusal":
                    raise ChybaModelu("odmitnuti", _SLUZBA, detail=str(obsah.refusal))

    def json(self, instrukce: str, zadani: str, schema: type[T], *, krok: str,
             effort: str | None = None) -> T:
        try:
            odp = self._klient.responses.parse(**self._spolecne(instrukce, zadani),
                                               text_format=schema)
            self._zpracuj(odp, krok)
            if odp.output_parsed is None:
                raise ChybaModelu("nevalidni_vystup", _SLUZBA, detail="chybí output_parsed",
                                  surova_odpoved=odp.output_text)
            return odp.output_parsed
        except ChybaModelu:
            raise
        except ValueError as exc:  # pydantic.ValidationError i JSONDecodeError z parse()
            raise ChybaModelu("nevalidni_vystup", _SLUZBA, detail=str(exc)) from exc
        except Exception as exc:
            raise prevod_vyjimky(exc, _SLUZBA) from exc

    def text(self, instrukce: str, zadani: str, *, krok: str) -> str:
        try:
            odp = self._klient.responses.create(**self._spolecne(instrukce, zadani))
            self._zpracuj(odp, krok)
            return odp.output_text
        except ChybaModelu:
            raise
        except Exception as exc:
            raise prevod_vyjimky(exc, _SLUZBA) from exc

    def vyzvedni_spotrebu(self) -> list[Spotreba]:
        spotreba, self._spotreba = self._spotreba, []
        return spotreba

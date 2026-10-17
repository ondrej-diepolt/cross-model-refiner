from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel

from refiner.data import Spotreba

T = TypeVar("T", bound=BaseModel)

Odpoved = BaseModel | dict | str | BaseException | Callable[[str, str], BaseModel | dict | str]


class FalesnyModel:
    def __init__(self, odpovedi: dict[str, list[Odpoved]], nazev: str = "falesny"):
        self.nazev = nazev
        self._odpovedi = {k: list(v) for k, v in odpovedi.items()}
        self.volani: list[tuple[str, str, str]] = []
        self._spotreba: list[Spotreba] = []

    def _vezmi(self, krok: str, instrukce: str, zadani: str):
        self.volani.append((krok, instrukce, zadani))
        klic = krok if self._odpovedi.get(krok) else krok.split("_", 1)[0]
        fronta = self._odpovedi.get(klic)
        if not fronta:
            raise AssertionError(f"Falešný model nemá odpověď pro krok {krok!r}")
        odpoved = fronta.pop(0)
        if isinstance(odpoved, BaseException):
            raise odpoved
        self._spotreba.append(Spotreba(krok=krok, model=self.nazev, vstup=1000, vystup=500))
        if callable(odpoved) and not isinstance(odpoved, BaseModel):
            odpoved = odpoved(instrukce, zadani)
        return odpoved

    def json(self, instrukce: str, zadani: str, schema: type[T], *, krok: str,
             effort: str | None = None) -> T:
        odpoved = self._vezmi(krok, instrukce, zadani)
        if isinstance(odpoved, schema):
            return odpoved
        if isinstance(odpoved, BaseModel):
            return schema.model_validate(odpoved.model_dump())
        if isinstance(odpoved, str):
            return schema.model_validate_json(odpoved)
        return schema.model_validate(odpoved)

    def text(self, instrukce: str, zadani: str, *, krok: str) -> str:
        odpoved = self._vezmi(krok, instrukce, zadani)
        if isinstance(odpoved, str):
            return odpoved
        if isinstance(odpoved, BaseModel):
            return odpoved.model_dump_json()
        return str(odpoved)

    def vyzvedni_spotrebu(self) -> list[Spotreba]:
        spotreba, self._spotreba = self._spotreba, []
        return spotreba

from typing import Protocol, TypeVar

from pydantic import BaseModel

from refiner.data import Spotreba

T = TypeVar("T", bound=BaseModel)


class Model(Protocol):
    nazev: str

    def json(self, instrukce: str, zadani: str, schema: type[T], *, krok: str,
             effort: str | None = None) -> T: ...

    def text(self, instrukce: str, zadani: str, *, krok: str) -> str: ...

    def vyzvedni_spotrebu(self) -> list[Spotreba]: ...

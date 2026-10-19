from typing import Protocol, TypeVar

from pydantic import BaseModel

from refiner.data import Spotreba as TokenUsage

T = TypeVar("T", bound=BaseModel)


class Model(Protocol):
    name: str

    def json(self, instructions: str, task: str, schema: type[T], *, step: str,
             effort: str | None = None) -> T: ...

    def text(self, instructions: str, task: str, *, step: str) -> str: ...

    def take_usage(self) -> list[TokenUsage]: ...

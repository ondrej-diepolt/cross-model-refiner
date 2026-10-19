"""Numbered run artifacts and atomic, versioned state at the preserved Czech path."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import AliasChoices, BaseModel, Field, model_validator

from refiner.artifacts import STATE_FILE, canonical_profile_id, output_profile_name
from refiner.data import ScoreResult, TokenUsage
from refiner.input import slug
from refiner.legacy import normalize_run_state

T = TypeVar("T", bound=BaseModel)


class StepRecord(BaseModel):
    number: int = Field(validation_alias=AliasChoices("number", "cislo"))
    file: str = Field(validation_alias=AliasChoices("file", "soubor"))
    data: str | None = None


class RunState(BaseModel):
    schema_version: Literal[2] = 2
    input: str
    profile_id: str
    output_profile_name: str
    created_at: datetime
    dry_run: bool = False
    ended_at: datetime | None = None
    status: Literal["running", "completed", "interrupted"] = "running"
    stop_reason: str | None = None
    error: str | None = None
    final_version: int | None = None
    steps: dict[str, StepRecord] = Field(default_factory=dict)
    scores: dict[str, ScoreResult] = Field(default_factory=dict)
    usage: list[TokenUsage] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    _decode_legacy = model_validator(mode="before")(normalize_run_state)


class Run:
    def __init__(self, directory: Path, state: RunState):
        self.directory = directory
        self.state = state

    @classmethod
    def new(cls, output: Path, input_name: str, profile_id: str, now: datetime,
            dry_run: bool = False) -> Run:
        base = f"{now:%Y-%m-%d_%H%M}_{slug(Path(input_name).stem)}"
        directory = output / base
        number = 2
        while directory.exists():
            directory = output / f"{base}_{number}"
            number += 1
        (directory / "data").mkdir(parents=True)
        profile_id = canonical_profile_id(profile_id)
        run = cls(directory, RunState(input=input_name, profile_id=profile_id,
                  output_profile_name=output_profile_name(profile_id), created_at=now, dry_run=dry_run))
        run.save()
        return run

    @classmethod
    def open(cls, directory: Path) -> Run:
        text = (directory / STATE_FILE).read_text(encoding="utf-8")
        return cls(directory, RunState.model_validate_json(text))

    def save(self) -> None:
        target = self.directory / STATE_FILE
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(self.state.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temporary, target)

    def _next_number(self) -> int:
        return max((record.number for record in self.state.steps.values()), default=0) + 1

    def write(self, step: str, name: str, content: str, data: BaseModel | None = None) -> Path:
        number = self._next_number()
        file = f"{number:02d}_{name}"
        path = self.write_fixed(file, content)
        relative_data = None
        if data is not None:
            relative_data = f"data/{number:02d}_{Path(name).stem}.json"
            self.write_fixed(relative_data, data.model_dump_json(indent=2))
        self.state.steps[step] = StepRecord(number=number, file=file, data=relative_data)
        self.save()
        return path

    def write_for_step(self, step: str, name: str, content: str) -> Path:
        number = self.state.steps[step].number
        return self.write_fixed(f"{number:02d}_{name}", content)

    def write_fixed(self, relative_path: str, content: str | bytes) -> Path:
        path = self.directory / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path

    def is_done(self, step: str) -> bool:
        return step in self.state.steps

    def text(self, step: str) -> str:
        return (self.directory / self.state.steps[step].file).read_text(encoding="utf-8")

    def data(self, step: str, model: type[T]) -> T:
        relative = self.state.steps[step].data
        if relative is None:
            raise KeyError(f"Krok {step} nemá uložená data")
        return model.model_validate_json((self.directory / relative).read_text(encoding="utf-8"))

    def add_usage(self, items: list[TokenUsage]) -> None:
        self.state.usage.extend(items)
        self.save()

    def add_warning(self, text: str) -> None:
        self.state.warnings.append(text)
        self.save()

    def save_score(self, number: int, score: ScoreResult) -> None:
        self.state.scores[str(number)] = score
        self.save()

    def finish(self, status: Literal["completed", "interrupted"], reason: str | None = None,
               error: str | None = None, final_version: int | None = None) -> None:
        self.state.status = status
        self.state.stop_reason = reason
        self.state.error = error
        self.state.final_version = final_version
        self.state.ended_at = datetime.now()
        self.save()

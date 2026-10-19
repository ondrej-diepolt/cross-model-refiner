"""Load and validate YAML settings, document profiles, and request criteria."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from refiner.artifacts import canonical_profile_id, output_profile_name

SUM_TOLERANCE = 1e-6


class ConfigurationError(Exception):
    """A Czech configuration error with source filename, line, and field path."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileCriterion(_Model):
    id: str
    name: str = Field(validation_alias=AliasChoices("name", "nazev"))
    description: str = Field(validation_alias=AliasChoices("description", "popis"))
    weight: float = Field(gt=0, validation_alias=AliasChoices("weight", "vaha"))


class Profile(_Model):
    name: str = Field(validation_alias=AliasChoices("name", "nazev"))
    document_type: str = Field(validation_alias=AliasChoices("document_type", "typ_dokumentu"))
    structure_instructions: str = Field(validation_alias=AliasChoices("structure_instructions", "pokyny_struktura"))
    criteria: list[ProfileCriterion] = Field(validation_alias=AliasChoices("criteria", "kriteria"))


# SDK effort values: anthropic 1.15.0 OutputConfigParam.effort and
# openai 3.33.0 shared.ReasoningEffort. Catch typos before model calls.
ClaudeEffort = Literal["low", "medium", "high", "xhigh", "max"]
GptEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]
CodexEffort = Literal["low", "medium", "high", "xhigh", "max"]


class ClaudeSettings(_Model):
    model: str
    effort: ClaudeEffort
    extraction_effort: ClaudeEffort = Field(validation_alias=AliasChoices("extraction_effort", "effort_extrakce"))
    max_tokens_text: int
    max_tokens_json: int
    fallback: bool


class GptSettings(_Model):
    model: str
    effort: GptEffort
    max_output_tokens: int


class ClaudeCliSettings(_Model):
    model: str = "claude-opus-5-5"
    effort: ClaudeEffort = "high"
    extraction_effort: ClaudeEffort = Field(default="medium", validation_alias=AliasChoices("extraction_effort", "effort_extrakce"))
    command: str | None = Field(default=None, validation_alias=AliasChoices("command", "prikaz"))


class CodexSettings(_Model):
    model: str = "gpt-6-astra"
    effort: CodexEffort = "high"
    command: str | None = Field(default=None, validation_alias=AliasChoices("command", "prikaz"))


class SubscriptionSettings(_Model):
    claude: ClaudeCliSettings = Field(default_factory=ClaudeCliSettings)
    codex: CodexSettings = Field(default_factory=CodexSettings)


class ModelSettings(_Model):
    claude: ClaudeSettings
    gpt: GptSettings
    max_retries: int
    timeout_s: float
    mode: Literal["subscription", "api"] = Field(default="subscription", validation_alias=AliasChoices("mode", "rezim"))
    subscription: SubscriptionSettings = Field(default_factory=SubscriptionSettings, validation_alias=AliasChoices("subscription", "predplatne"))

    @field_validator("mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value):
        return "subscription" if value == "predplatne" else value

    @model_validator(mode="after")
    def _extraction_effort_for_mode(self) -> ModelSettings:
        # Steps read claude.extraction_effort in both modes.
        if self.mode == "subscription":
            self.claude = self.claude.model_copy(update={"extraction_effort": self.subscription.claude.extraction_effort})
        return self


class LoopSettings(_Model):
    target_score: float = Field(validation_alias=AliasChoices("target_score", "cilove_skore"))
    max_revisions: int = Field(ge=0, validation_alias=AliasChoices("max_revisions", "max_revizi"))
    min_requirement_score: float = Field(validation_alias=AliasChoices("min_requirement_score", "min_nalezitost"))
    max_suggestions: int = Field(ge=1, validation_alias=AliasChoices("max_suggestions", "max_navrhu"))


class Price(_Model):
    """USD per million tokens."""

    input: float = Field(validation_alias=AliasChoices("input", "vstup"))
    output: float = Field(validation_alias=AliasChoices("output", "vystup"))


class Settings(_Model):
    models: ModelSettings = Field(validation_alias=AliasChoices("models", "modely"))
    loop: LoopSettings = Field(validation_alias=AliasChoices("loop", "smycka"))
    group_weights: dict[Literal["A", "B", "C"], float] = Field(validation_alias=AliasChoices("group_weights", "vahy_skupin"))
    default_profile: str = Field(validation_alias=AliasChoices("default_profile", "vychozi_profil"))
    prices_usd_per_million: dict[str, Price] = Field(validation_alias=AliasChoices("prices_usd_per_million", "ceny_usd_za_milion"))

    @field_validator("default_profile", mode="before")
    @classmethod
    def _normalize_default_profile(cls, value):
        return canonical_profile_id(value) if isinstance(value, str) else value


class RequestCriteria(_Model):
    extra_criteria: list[ProfileCriterion] = Field(default_factory=list, validation_alias=AliasChoices("extra_criteria", "kriteria_navic"))
    weights: dict[str, float] = Field(default_factory=dict, validation_alias=AliasChoices("weights", "vahy"))


@dataclass(frozen=True)
class Configuration:
    settings: Settings
    profile: Profile
    profile_id: str
    profile_criteria: list[ProfileCriterion]
    output_profile_name: str


def _error(file: Path, line: int | None, path: str, text: str) -> ConfigurationError:
    line_part = f", řádek {line}" if line else ""
    path_part = f"{path}: " if path else ""
    return ConfigurationError(f"{file.name}{line_part}: {path_part}{text}")


def _node_line(root: yaml.Node | None, location: tuple) -> int | None:
    """Return a one-based node line, or the nearest available ancestor's line."""
    node = root
    if node is None:
        return None
    for key in location:
        if isinstance(node, yaml.MappingNode):
            next_node = next((v for k, v in node.value if k.value == key), None)
        elif isinstance(node, yaml.SequenceNode) and isinstance(key, int) and key < len(node.value):
            next_node = node.value[key]
        else:
            next_node = None
        if next_node is None:
            break
        node = next_node
    return node.start_mark.line + 1


def _source_key(root: yaml.Node | None, canonical: str, legacy: str) -> str:
    """Use the spelling actually present in the YAML for manual error locations."""
    keys = {key.value for key, _ in root.value} if isinstance(root, yaml.MappingNode) else set()
    return canonical if canonical in keys or legacy not in keys else legacy


def _read_yaml(file: Path) -> tuple[object, yaml.Node | None]:
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigurationError(f"{file.name}: soubor nelze přečíst ({exc.strerror or exc})") from exc
    try:
        data = yaml.safe_load(text)
        root = yaml.compose(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = mark.line + 1 if mark else None
        problem = getattr(exc, "problem", None) or str(exc)
        raise _error(file, line, "", f"neplatný YAML ({problem})") from exc
    return data, root


def _czech_error(error: dict) -> str:
    kind = error["type"]
    if kind == "missing":
        return "chybí povinná položka"
    if kind in ("float_parsing", "float_type", "int_parsing", "int_type", "int_from_float"):
        return f"musí být číslo, je ‚{error.get('input')}‘"
    if kind == "extra_forbidden":
        return "neznámá položka (překlep?)"
    if kind == "greater_than":
        return f"musí být větší než {error['ctx']['gt']}"
    if kind == "greater_than_equal":
        return f"musí být alespoň {error['ctx']['ge']}"
    if kind == "literal_error":
        options = str(error["ctx"]["expected"]).replace(" or ", " nebo ")
        return f"‚{error.get('input')}‘ není povolená hodnota, musí být jedna z: {options}"
    return error["msg"]


def _validate(model: type[_Model], file: Path):
    data, root = _read_yaml(file)
    try:
        return model.model_validate({} if data is None else data), root
    except ValidationError as exc:
        error = exc.errors()[0]
        location = tuple(error["loc"])
        path = ".".join(str(part) for part in location)
        raise _error(file, _node_line(root, location), path, _czech_error(error)) from exc


def _check_ids(criteria: list[ProfileCriterion], file: Path, root, path: str) -> None:
    seen: set[str] = set()
    for i, criterion in enumerate(criteria):
        line = _node_line(root, (path, i, "id"))
        if criterion.id.upper().startswith("N"):
            raise _error(file, line, f"{path}.{i}.id", f"ID ‚{criterion.id}‘ nesmí začínat písmenem N (vyhrazeno pro náležitosti)")
        if criterion.id in seen:
            raise _error(file, line, f"{path}.{i}.id", f"duplicitní ID kritéria ‚{criterion.id}‘")
        seen.add(criterion.id)


def load_settings(path: Path) -> Settings:
    """Load and validate settings independently of a document profile."""
    settings, root = _validate(Settings, path)
    total = sum(settings.group_weights.values())
    if abs(total - 1.0) > SUM_TOLERANCE or set(settings.group_weights) != {"A", "B", "C"}:
        key = _source_key(root, "group_weights", "vahy_skupin")
        raise _error(path, _node_line(root, (key,)), key, f"váhy skupin A, B, C musí mít součet 1, je {total:g}")
    return settings


def load_configuration(settings: Path, profile: Path, criteria: Path | None = None) -> Configuration:
    loaded_settings = load_settings(settings)
    loaded_profile, profile_root = _validate(Profile, profile)
    _check_ids(loaded_profile.criteria, profile, profile_root, _source_key(profile_root, "criteria", "kriteria"))
    combined = list(loaded_profile.criteria)
    if criteria is not None:
        sidecar, root = _validate(RequestCriteria, criteria)
        extra_key = _source_key(root, "extra_criteria", "kriteria_navic")
        weights_key = _source_key(root, "weights", "vahy")
        _check_ids(sidecar.extra_criteria, criteria, root, extra_key)
        ids = {criterion.id for criterion in loaded_profile.criteria}
        for i, criterion in enumerate(sidecar.extra_criteria):
            if criterion.id in ids:
                raise _error(criteria, _node_line(root, (extra_key, i, "id")), f"{extra_key}.{i}.id", f"duplicitní ID kritéria ‚{criterion.id}‘")
        combined += sidecar.extra_criteria
        ids = {criterion.id for criterion in combined}
        for id_, weight in sidecar.weights.items():
            line = _node_line(root, (weights_key, id_))
            if id_ not in ids:
                raise _error(criteria, line, f"{weights_key}.{id_}", f"neznámé ID kritéria ‚{id_}‘ (dostupná: {', '.join(sorted(ids))})")
            if weight <= 0:
                raise _error(criteria, line, f"{weights_key}.{id_}", "musí být větší než 0")
        combined = [criterion.model_copy(update={"weight": sidecar.weights.get(criterion.id, criterion.weight)}) for criterion in combined]
    profile_id = canonical_profile_id(profile.stem)
    return Configuration(loaded_settings, loaded_profile, profile_id, combined, output_profile_name(profile_id))


def criteria_path_for_request(request: Path) -> Path | None:
    for suffix in (".criteria.yaml", ".kriteria.yaml"):
        path = request.with_suffix(suffix)
        if path.exists():
            return path
    return None


def available_profiles(directory: Path) -> list[str]:
    # Preserve the Czech menu order when built-in technical identifiers change.
    return sorted((path.stem for path in directory.glob("*.yaml")), key=output_profile_name)

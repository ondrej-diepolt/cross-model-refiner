"""Domain schemas use English output keys and validation-only aliases for saved Czech JSON.

Structured model outputs intentionally have no defaults or numeric range constraints.
"""
from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator

from refiner.configuration import ProfileCriterion
from refiner.legacy import DECISIONS, PRIORITIES, normalize_step_id


class Requirement(BaseModel):
    id: str
    text: str
    citation: str = Field(validation_alias=AliasChoices('citation', 'citace'))


class RequirementsOutput(BaseModel):
    requirements: list[Requirement] = Field(validation_alias=AliasChoices('requirements', 'nalezitosti'))


class Criterion(BaseModel):
    id: str
    name: str = Field(validation_alias=AliasChoices('name', 'nazev'))
    description: str = Field(validation_alias=AliasChoices('description', 'popis'))
    weight: float = Field(validation_alias=AliasChoices('weight', 'vaha'))
    group: Literal["A", "B"] = Field(validation_alias=AliasChoices('group', 'skupina'))


class CriterionScore(BaseModel):
    id: str
    score: float = Field(validation_alias=AliasChoices('score', 'skore'))
    rationale: str = Field(validation_alias=AliasChoices('rationale', 'zduvodneni'))
    evidence: str = Field(validation_alias=AliasChoices('evidence', 'dukaz'))


class FabricatedFact(BaseModel):
    citation: str = Field(validation_alias=AliasChoices('citation', 'citace'))
    reason: str = Field(validation_alias=AliasChoices('reason', 'proc'))


class ClaimToVerify(BaseModel):
    citation: str = Field(validation_alias=AliasChoices('citation', 'citace'))
    reason: str = Field(validation_alias=AliasChoices('reason', 'proc'))


class RevisionSuggestion(BaseModel):
    id: str
    criterion: str = Field(validation_alias=AliasChoices('criterion', 'kriterium'))
    location: str = Field(validation_alias=AliasChoices('location', 'misto'))
    problem: str
    suggestion: str = Field(validation_alias=AliasChoices('suggestion', 'navrh'))
    priority: Literal["high", "medium", "low"] = Field(validation_alias=AliasChoices('priority', 'priorita'))

    @field_validator("priority", mode="before")
    @classmethod
    def _normalize_priority(cls, value):
        return PRIORITIES.get(value, value) if isinstance(value, str) else value


class Evaluation(BaseModel):
    criteria: list[CriterionScore] = Field(validation_alias=AliasChoices('criteria', 'kriteria'))
    fabricated_facts: list[FabricatedFact] = Field(validation_alias=AliasChoices('fabricated_facts', 'vymyslena_fakta'))
    claims_to_verify: list[ClaimToVerify] = Field(validation_alias=AliasChoices('claims_to_verify', 'tvrzeni_k_overeni'))
    suggestions: list[RevisionSuggestion] = Field(validation_alias=AliasChoices('suggestions', 'navrhy'))
    overall_comment: str = Field(validation_alias=AliasChoices('overall_comment', 'celkovy_komentar'))


class SuggestionDecision(BaseModel):
    suggestion_id: str = Field(validation_alias=AliasChoices('suggestion_id', 'id_navrhu'))
    support: str = Field(validation_alias=AliasChoices('support', 'opora'))
    assumption: str = Field(validation_alias=AliasChoices('assumption', 'predpoklad'))
    consequence: str = Field(validation_alias=AliasChoices('consequence', 'dusledek'))
    decision: Literal["accepted", "partial", "rejected"] = Field(validation_alias=AliasChoices('decision', 'rozhodnuti'))
    rationale: str = Field(validation_alias=AliasChoices('rationale', 'zduvodneni'))
    implementation: str = Field(validation_alias=AliasChoices('implementation', 'jak_zapracovat'))

    @field_validator("decision", mode="before")
    @classmethod
    def _normalize_decision(cls, value):
        return DECISIONS.get(value, value) if isinstance(value, str) else value


class SuggestionReview(BaseModel):
    decisions: list[SuggestionDecision] = Field(validation_alias=AliasChoices('decisions', 'rozhodnuti'))
    summary: str = Field(validation_alias=AliasChoices('summary', 'shrnuti'))


class ScoreResult(BaseModel):
    a: float
    b: float
    c: float
    total: float = Field(validation_alias=AliasChoices('total', 'celkem'))
    target_met: bool = Field(validation_alias=AliasChoices('target_met', 'cil_splnen'))
    unmet_reasons: list[str] = Field(validation_alias=AliasChoices('unmet_reasons', 'duvody_nesplneni'))


class TokenUsage(BaseModel):
    step: str = Field(validation_alias=AliasChoices('step', 'krok'))
    model: str
    input_tokens: int = Field(validation_alias=AliasChoices('input_tokens', 'vstup'))
    output_tokens: int = Field(validation_alias=AliasChoices('output_tokens', 'vystup'))
    cache_read_tokens: int = Field(default=0, validation_alias=AliasChoices('cache_read_tokens', 'cache_cteni'))
    cache_write_tokens: int = Field(default=0, validation_alias=AliasChoices('cache_write_tokens', 'cache_zapis'))
    subscription: bool = Field(default=False, validation_alias=AliasChoices('subscription', 'predplatne'))

    @field_validator("step", mode="before")
    @classmethod
    def _normalize_step(cls, value):
        return normalize_step_id(value) if isinstance(value, str) else value


def build_criteria(requirements: list[Requirement], profile_criteria: list[ProfileCriterion]) -> list[Criterion]:
    """Group A contains equally weighted requirements; group B contains profile criteria."""
    a = [Criterion(id=n.id, name=n.text, description=n.citation, weight=1, group="A") for n in requirements]
    b = [Criterion(id=k.id, name=k.name, description=k.description, weight=k.weight, group="B")
         for k in profile_criteria]
    return a + b

"""Offline test builders for settings, criteria, evaluations, and scripted models."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from refiner.run import Run
from refiner.data import (
    Evaluation,
    Requirement,
    RevisionSuggestion,
    SuggestionReview,
    SuggestionDecision,
    CriterionScore,
    FabricatedFact,
    RequirementsOutput,
    Criterion,
    build_criteria,
)
from refiner.configuration import Settings, load_configuration
from refiner.steps import Sources
from refiner.models.fakes import FakeModel

ROOT = Path(__file__).parent.parent

TEST_REQUEST = """# Poptávka – tabletop cvičení

Zadavatel poptává přípravu a vedení tabletop cvičení pro krizový štáb (do 20 osob).

Nabídka proto musí obsahovat:
- popis metodiky cvičení,
- harmonogram a hlavní milníky realizace,
- cenu za celé plnění.
"""


TEST_REQUIREMENTS = [
    Requirement(id="N1", text="Metodika", citation="popis metodiky cvičení"),
    Requirement(id="N2", text="Harmonogram", citation="harmonogram a hlavní milníky realizace"),
    Requirement(id="N3", text="Cena", citation="cenu za celé plnění"),
]


def make_sources(repo_root: Path) -> Sources:
    """Short request, no materials, and repository configuration and prompts."""
    configuration = load_configuration(repo_root / "settings.yaml", repo_root / "profiles" / "proposal.yaml")
    return Sources(request=TEST_REQUEST, materials="", configuration=configuration, prompts=repo_root / 'prompts')


def make_settings() -> Settings:
    return load_configuration(ROOT / "settings.yaml", ROOT / "profiles" / "proposal.yaml").settings


def make_criteria(requirement_count: int = 3) -> list[Criterion]:
    configuration = load_configuration(ROOT / "settings.yaml", ROOT / "profiles" / "proposal.yaml")
    requirements = [Requirement(id=f"N{i}", text=f"Náležitost {i}", citation=f"Citace {i}")
           for i in range(1, requirement_count + 1)]
    return build_criteria(requirements, configuration.profile_criteria)


def make_evaluation(
    base: float = 8.0,
    overrides: dict[str, float] | None = None,
    facts: int = 0,
    suggestions: int = 2,
    criteria: list[Criterion] | None = None,
) -> Evaluation:
    criteria = criteria if criteria is not None else make_criteria()
    overrides = overrides or {}
    return Evaluation(
        criteria=[
            CriterionScore(id=k.id, score=overrides.get(k.id, base), rationale="Zdůvodnění.", evidence="Důkaz.")
            for k in criteria
        ],
        fabricated_facts=[FabricatedFact(citation=f"Fakt {i}", reason="Není ve vstupu.") for i in range(facts)],
        claims_to_verify=[],
        suggestions=[
            RevisionSuggestion(id=f"V{i}", criterion="B1", location=f"Místo {i}", problem="Problém.",
                  suggestion="Návrh.", priority='medium')
            for i in range(1, suggestions + 1)
        ],
        overall_comment="Komentář.",
    )


def make_review(h: Evaluation, decision: str = 'accepted') -> SuggestionReview:
    return SuggestionReview(
        decisions=[
            SuggestionDecision(suggestion_id=n.id, support="Opora.", assumption="Předpoklad.", consequence="Důsledek.",
                       decision=decision, rationale="Zdůvodnění.", implementation="Takto.")
            for n in h.suggestions
        ],
        summary="Shrnutí.",
    )


def make_run(tmp_path: Path, sources: Sources) -> Run:
    """New run with request already recorded, matching the real application flow."""
    run = Run.new(tmp_path, "poptavka.md", sources.configuration.profile_id, datetime(2026, 10, 17, 9, 0))
    run.write('request', "poptavka.md", sources.request)
    return run


def draft_text(version: int) -> str:
    """Short document with stable headings and comparable revision lengths."""
    return f"# Nabídka\n\nVerze {version}: popis metodiky cvičení, harmonogram a cena za celé plnění."


def scripted_responses(
    evaluation_scores: list[float], decision: str = 'accepted'
) -> tuple[dict[str, list], dict[str, list]]:
    """Responses keyed by exact loop step IDs; scores must be 1-10 in half steps."""
    for s in evaluation_scores:
        if not (1 <= s <= 10 and s * 2 == int(s * 2)):
            raise ValueError(f"script: score {s} must be 1–10 in increments of 0,5 to pass evaluation validation")
    writer: dict[str, list] = {
        'requirements': [RequirementsOutput(requirements=TEST_REQUIREMENTS)],
        'draft_1': [draft_text(1)],
    }
    evaluator: dict[str, list] = {}
    for k, scores in enumerate(evaluation_scores, start=1):
        h = make_evaluation(scores)
        evaluator[f"evaluation_{k}"] = [h]
        writer[f"review_{k}"] = [make_review(h, decision)]
        writer[f"draft_{k + 1}"] = [draft_text(k + 1)]
    return writer, evaluator


def scripted_models(
    evaluation_scores: list[float], decision: str = 'accepted'
) -> tuple[FakeModel, FakeModel]:
    """Fake writer and evaluator with identical criterion scores in each evaluation."""
    writer, evaluator = scripted_responses(evaluation_scores, decision)
    return FakeModel(writer, name="claude-falesny"), FakeModel(evaluator, name="gpt-falesny")

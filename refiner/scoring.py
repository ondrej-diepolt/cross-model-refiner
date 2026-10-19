"""Calculate scores and target checks in code, never in a model."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from refiner.data import Evaluation, Criterion, ScoreResult
from refiner.configuration import Settings

_TENTH = Decimal("0.1")


def _d(x: float) -> Decimal:
    return Decimal(str(x))


def _round(x: Decimal) -> Decimal:
    return x.quantize(_TENTH, rounding=ROUND_HALF_UP)


def format_score(x: float) -> str:
    return f"{_round(_d(x))}".replace(".", ",")


def fact_score(fact_count: int) -> float:
    """Ten without fabricated facts, otherwise max(1, 10 - 3 * count)."""
    if fact_count <= 0:
        return 10.0
    return float(max(1, 10 - 3 * fact_count))


def calculate_score(evaluation: Evaluation, criteria: list[Criterion], settings: Settings) -> ScoreResult:
    scores = {s.id: _d(s.score) for s in evaluation.criteria}
    a_criteria = [k for k in criteria if k.group == "A" and k.id in scores]
    b_criteria = [k for k in criteria if k.group == "B" and k.id in scores]

    a = sum((scores[k.id] for k in a_criteria), Decimal(0)) / len(a_criteria) if a_criteria else Decimal(0)
    weight_sum = sum((_d(k.weight) for k in b_criteria), Decimal(0))
    b = sum((scores[k.id] * _d(k.weight) for k in b_criteria), Decimal(0)) / weight_sum if weight_sum else Decimal(0)
    fact_count = len(evaluation.fabricated_facts)
    c = _d(fact_score(fact_count))

    v = settings.group_weights
    total = _round(_d(v["A"]) * a + _d(v["B"]) * b + _d(v["C"]) * c)

    reasons: list[str] = []
    target = _d(settings.loop.target_score)
    if total < target:
        reasons.append(f"celkové skóre {format_score(float(total))} < {format_score(float(target))}")
    minimum = _d(settings.loop.min_requirement_score)
    for k in a_criteria:
        if scores[k.id] < minimum:
            reasons.append(
                f"náležitost {k.id} má skóre {format_score(float(scores[k.id]))}, "
                f"minimum je {format_score(float(minimum))}"
            )
    if fact_count > 0:
        reasons.append(f"text obsahuje vymyšlené fakty ({fact_count})")

    return ScoreResult(
        a=float(_round(a)),
        b=float(_round(b)),
        c=float(c),
        total=float(total),
        target_met=not reasons,
        unmet_reasons=reasons,
    )


def select_final_version(scores: dict[int, ScoreResult]) -> int:
    """Select by target met, then highest total, then later version.

    A higher score blocked by a requirement minimum or fabricated fact cannot beat
    a version that met the target."""
    return max(scores, key=lambda version: (scores[version].target_met, scores[version].total, version))

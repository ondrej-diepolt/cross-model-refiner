"""Czech Markdown reports for requirements, evaluations, and suggestion reviews."""
from __future__ import annotations

from refiner.data import Evaluation, Criterion, Requirement, SuggestionReview, ScoreResult
from refiner.scoring import format_score

DECISION_LABELS = {'accepted': "přijato", 'partial': "částečně", 'rejected': "odmítnuto"}
PRIORITY_LABELS = {"high": "vysoka", "medium": "stredni", "low": "nizka"}


def cell(text: object) -> str:
    """Safe table cell text with normalized whitespace and escaped pipes."""
    return " ".join(str(text).split()).replace("|", chr(92) + "|")


def _row(*cells: object) -> str:
    return "| " + " | ".join(cell(b) for b in cells) + " |"


def requirements_markdown(requirements: list[Requirement], warnings: list[str]) -> str:
    r = ["# Náležitosti nabídky", "", "| ID | Náležitost | Citace z poptávky |", "|---|---|---|"]
    r += [_row(n.id, n.text, n.citation) for n in requirements]
    if warnings:
        r += ["", "## Varování", ""] + [f"- {v}" for v in warnings]
    return "\n".join(r) + "\n"


def evaluation_markdown(number: int, evaluation: Evaluation, score: ScoreResult, criteria: list[Criterion]) -> str:
    names = {k.id: k.name for k in criteria}
    r = [
        f"# Hodnocení {number}",
        "",
        f"- Skupina A (náležitosti): {format_score(score.a)}",
        f"- Skupina B (kvalita): {format_score(score.b)}",
        f"- Skupina C (vymyšlená fakta): {format_score(score.c)}",
        f"- **Celkem: {format_score(score.total)}**",
        f"- Cíl splněn: {'ano' if score.target_met else 'ne'}",
    ]
    if score.unmet_reasons:
        r += ["", "Důvody nesplnění:", ""] + [f"- {d}" for d in score.unmet_reasons]
    r += ["", "## Kritéria", "", "| ID | Název | Skóre | Zdůvodnění | Důkaz |", "|---|---|---|---|---|"]
    r += [_row(s.id, names.get(s.id, ""), format_score(s.score), s.rationale, s.evidence) for s in evaluation.criteria]
    r += ["", "## Vymyšlená fakta", ""]
    r += [f"- {cell(f.citation)} – {cell(f.reason)}" for f in evaluation.fabricated_facts] or ["Žádná."]
    r += ["", "## Tvrzení k ověření", ""]
    r += [f"- {cell(t.citation)} – {cell(t.reason)}" for t in evaluation.claims_to_verify] or ["Žádná."]
    r += ["", "## Návrhy", ""]
    if evaluation.suggestions:
        r += ["| ID | Kritérium | Místo | Problém | Návrh | Priorita |", "|---|---|---|---|---|---|"]
        r += [_row(n.id, n.criterion, n.location, n.problem, n.suggestion, PRIORITY_LABELS[n.priority]) for n in evaluation.suggestions]
    else:
        r.append("Žádné.")
    r += ["", "## Celkový komentář", "", evaluation.overall_comment]
    return "\n".join(r) + "\n"


def review_markdown(number: int, evaluation: Evaluation, review: SuggestionReview) -> str:
    suggestions = {n.id: n for n in evaluation.suggestions}
    count = {k: sum(1 for x in review.decisions if x.decision == k) for k in DECISION_LABELS}
    r = [
        f"# Posouzení návrhů z hodnocení {number}",
        "",
        f"Přijato: {count['accepted']} · Částečně: {count['partial']} · Odmítnuto: {count['rejected']}",
        "",
        review.summary,
    ]
    for x in review.decisions:
        n = suggestions.get(x.suggestion_id)
        r += ["", f"## Návrh {x.suggestion_id}", ""]
        if n:
            r += [f"- Místo: {cell(n.location)}", f"- Znění návrhu: {cell(n.suggestion)}"]
        r += [
            f"- Opora: {x.support}",
            f"- Předpoklad: {x.assumption}",
            f"- Důsledek: {x.consequence}",
            f"- **Rozhodnutí: {DECISION_LABELS[x.decision]}**",
            f"- Zdůvodnění: {x.rationale}",
            f"- Jak zapracovat: {x.implementation}",
        ]
    return "\n".join(r) + "\n"

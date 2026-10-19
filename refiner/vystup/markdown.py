"""Lidsky čitelné Markdown výstupy: náležitosti, hodnocení, posouzení."""
from __future__ import annotations

from refiner.data import Evaluation, Criterion, Requirement, SuggestionReview, ScoreResult
from refiner.scoring import format_score

_POPISKY = {'accepted': "přijato", 'partial': "částečně", 'rejected': "odmítnuto"}
PRIORITY_LABELS = {"high": "vysoka", "medium": "stredni", "low": "nizka"}


def bunka(text: object) -> str:
    """Text bezpečný do buňky tabulky: bez zalomení řádků a s escapovaným svislítkem."""
    return " ".join(str(text).split()).replace("|", chr(92) + "|")


def _radek(*bunky: object) -> str:
    return "| " + " | ".join(bunka(b) for b in bunky) + " |"


def nalezitosti_md(nalezitosti: list[Requirement], varovani: list[str]) -> str:
    r = ["# Náležitosti nabídky", "", "| ID | Náležitost | Citace z poptávky |", "|---|---|---|"]
    r += [_radek(n.id, n.text, n.citation) for n in nalezitosti]
    if varovani:
        r += ["", "## Varování", ""] + [f"- {v}" for v in varovani]
    return "\n".join(r) + "\n"


def hodnoceni_md(cislo: int, h: Evaluation, skore: ScoreResult, kriteria: list[Criterion]) -> str:
    nazvy = {k.id: k.name for k in kriteria}
    r = [
        f"# Hodnocení {cislo}",
        "",
        f"- Skupina A (náležitosti): {format_score(skore.a)}",
        f"- Skupina B (kvalita): {format_score(skore.b)}",
        f"- Skupina C (vymyšlená fakta): {format_score(skore.c)}",
        f"- **Celkem: {format_score(skore.total)}**",
        f"- Cíl splněn: {'ano' if skore.target_met else 'ne'}",
    ]
    if skore.unmet_reasons:
        r += ["", "Důvody nesplnění:", ""] + [f"- {d}" for d in skore.unmet_reasons]
    r += ["", "## Kritéria", "", "| ID | Název | Skóre | Zdůvodnění | Důkaz |", "|---|---|---|---|---|"]
    r += [_radek(s.id, nazvy.get(s.id, ""), format_score(s.score), s.rationale, s.evidence) for s in h.criteria]
    r += ["", "## Vymyšlená fakta", ""]
    r += [f"- {bunka(f.citation)} – {bunka(f.reason)}" for f in h.fabricated_facts] or ["Žádná."]
    r += ["", "## Tvrzení k ověření", ""]
    r += [f"- {bunka(t.citation)} – {bunka(t.reason)}" for t in h.claims_to_verify] or ["Žádná."]
    r += ["", "## Návrhy", ""]
    if h.suggestions:
        r += ["| ID | Kritérium | Místo | Problém | Návrh | Priorita |", "|---|---|---|---|---|---|"]
        r += [_radek(n.id, n.criterion, n.location, n.problem, n.suggestion, PRIORITY_LABELS[n.priority]) for n in h.suggestions]
    else:
        r.append("Žádné.")
    r += ["", "## Celkový komentář", "", h.overall_comment]
    return "\n".join(r) + "\n"


def posouzeni_md(cislo: int, h: Evaluation, p: SuggestionReview) -> str:
    navrhy = {n.id: n for n in h.suggestions}
    pocet = {k: sum(1 for x in p.decisions if x.decision == k) for k in _POPISKY}
    r = [
        f"# Posouzení návrhů z hodnocení {cislo}",
        "",
        f"Přijato: {pocet['accepted']} · Částečně: {pocet['partial']} · Odmítnuto: {pocet['rejected']}",
        "",
        p.summary,
    ]
    for x in p.decisions:
        n = navrhy.get(x.suggestion_id)
        r += ["", f"## Návrh {x.suggestion_id}", ""]
        if n:
            r += [f"- Místo: {bunka(n.location)}", f"- Znění návrhu: {bunka(n.suggestion)}"]
        r += [
            f"- Opora: {x.support}",
            f"- Předpoklad: {x.assumption}",
            f"- Důsledek: {x.consequence}",
            f"- **Rozhodnutí: {_POPISKY[x.decision]}**",
            f"- Zdůvodnění: {x.rationale}",
            f"- Jak zapracovat: {x.implementation}",
        ]
    return "\n".join(r) + "\n"

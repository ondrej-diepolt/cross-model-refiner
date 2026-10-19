"""Prompt rendering, model calls, output validation, and one repair attempt."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import unicodedata
from string import Template
from typing import TypeVar

from refiner.data import (
    Evaluation,
    Criterion,
    Requirement,
    RevisionSuggestion,
    SuggestionReview,
    SuggestionDecision,
    RequirementsOutput,
    build_criteria,
)
from refiner.configuration import ConfigurationError, Configuration
from refiner.models.errors import ModelError, Service
from refiner.models.interface import Model
from refiner.artifacts import PROMPT_SNAPSHOT_NAMES
from refiner.legacy import adapt_legacy_prompt, prompt_variables
from refiner.vystup.markdown import PRIORITY_LABELS

T = TypeVar("T")

EMPTY_MATERIALS = "(Profil firmy nebyl dodán – všechna fakta o dodavateli označ [DOPLNIT: …].)"
NO_REJECTIONS = "(žádné)"
MIN_LENGTH_RATIO = 0.7
PRIORITY_ORDER = {'high': 0, 'medium': 1, 'low': 2}
# Czech word stems compared against accent-stripped suggestion text (odstraň -> odstran).
SHORTENING_WORDS = ("zkrat", "odstran", "vypust", "smaz", "zrus")

REQUIREMENTS_TASK = "Vypiš povinné náležitosti z poptávky výše podle pokynů."
DRAFT_TASK = "Napiš dokument podle pokynů výše."


@dataclass(frozen=True)
class Sources:
    request: str
    materials: str
    configuration: Configuration
    prompts: Path


# ---------------------------------------------------------------- prompts

def render_prompt(directory: Path, name: str, **variables: str) -> str:
    name = name.removesuffix(".md")
    file = directory / f"{name}.md"
    if not file.is_file() and name in PROMPT_SNAPSHOT_NAMES:
        file = directory / PROMPT_SNAPSHOT_NAMES[name]
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigurationError(f"{file.name}: prompt nelze přečíst ({e.strerror or e})") from e
    try:
        return Template(adapt_legacy_prompt(text, name)).substitute(prompt_variables(variables))
    except KeyError as e:
        available = ", ".join(sorted(variables)) or "žádné"
        raise ConfigurationError(
            f"{file.name}: neznámá proměnná ${{{e.args[0]}}} (dostupné proměnné: {available})"
        ) from e
    except ValueError as e:
        raise ConfigurationError(
            f"{file.name}: neplatný zápis proměnné ({e}); znak $ v textu pište jako $$"
        ) from e


def common_variables(sources: Sources) -> dict[str, str]:
    return {
        'request': sources.request,
        'materials': sources.materials if sources.materials.strip() else EMPTY_MATERIALS,
    }


def _requirements_text(requirements: list[Requirement]) -> str:
    return "\n".join(f"- **{n.id}** {n.text} – citace z poptávky: „{n.citation}“" for n in requirements)


def criteria_text(criteria: list[Criterion]) -> str:
    lines = []
    for k in criteria:
        if k.group == "A":
            lines.append(f"- **{k.id}** (A – povinná náležitost) {k.name}. Citace z poptávky: „{k.description}“")
        else:
            lines.append(f"- **{k.id}** (B – obecná kvalita) {k.name}: {k.description}")
    return "\n".join(lines)


def _rejected_text(rejected_suggestions: list[tuple[RevisionSuggestion, SuggestionDecision]]) -> str:
    if not rejected_suggestions:
        return NO_REJECTIONS
    blocks = []
    for n, r in rejected_suggestions:
        blocks.append(
            f"- Kritérium {n.criterion}, místo: {n.location}\n"
            f"  - Problém: {n.problem}\n"
            f"  - Návrh: {n.suggestion}\n"
            f"  - Důvod odmítnutí: {r.rationale}"
        )
    return "\n".join(blocks)


def document_section(document: str) -> str:
    return f"## Dokument\n\n<dokument>\n{document}\n</dokument>"


def _suggestions_text(suggestions: list[RevisionSuggestion]) -> str:
    return "\n\n".join(
        f"### {n.id} (kritérium {n.criterion}, priorita {PRIORITY_LABELS[n.priority]})\n"
        f"- Místo: {n.location}\n- Problém: {n.problem}\n- Návrh: {n.suggestion}"
        for n in suggestions
    )


def _accepted_text(evaluation: Evaluation, review: SuggestionReview) -> str:
    by_id = {n.id: n for n in evaluation.suggestions}
    blocks = []
    for r in accepted_decisions(review):
        state = "přijato" if r.decision == 'accepted' else "přijato částečně"
        lines = [f"### {r.suggestion_id} ({state})"]
        n = by_id.get(r.suggestion_id)
        if n is not None:
            lines += [f"- Místo: {n.location}", f"- Problém: {n.problem}", f"- Návrh hodnotitele: {n.suggestion}"]
        lines.append(f"- Jak zapracovat: {r.implementation}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _clean_document(text: str) -> str:
    """Remove wrappers sometimes added by the model despite the document-only instruction."""
    t = text.strip()
    lines = t.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        t = "\n".join(lines[1:-1]).strip()
    if t.startswith("<dokument>") and t.endswith("</dokument>"):
        t = t[len("<dokument>"):-len("</dokument>")].strip()
    return t


# ---------------------------------------------------------------- calls with one repair

def _service(model: Model) -> Service:
    return "OpenAI" if model.name.lower().startswith("gpt") else "Anthropic"


def with_repair(
    model: Model,
    task: str,
    call: Callable[[str], T],
    validate: Callable[[T], list[str]],
    raw: Callable[[T], str],
) -> T:
    """Call at most twice; the second task includes validation errors from the first response."""
    errors: list[str] = []
    raw_response: str | None = None
    for attempt in range(2):
        z = task if attempt == 0 else f"{task}\n\n## Oprava\nPředchozí odpověď byla neplatná: {'; '.join(errors)}"
        try:
            result = call(z)
        except ModelError as e:
            if e.kind != 'invalid_output':
                raise
            errors = [e.detail or e.message]
            raw_response = e.raw_response
            continue
        errors = validate(result)
        if not errors:
            return result
        raw_response = raw(result)
    raise ModelError('invalid_output', _service(model), detail="; ".join(errors), raw_response=raw_response)


# ---------------------------------------------------------------- validation

def _number(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _partition_requirements(
    output: RequirementsOutput, request: str
) -> tuple[list[Requirement], list[str]]:
    """Keep requirements whose whitespace-normalized citations occur verbatim in the request."""
    text = _normalize(request)
    valid, warnings = [], []
    for n in output.requirements:
        if _normalize(n.citation) and _normalize(n.citation) in text:
            valid.append(n)
        else:
            warnings.append(
                f"Náležitost {n.id} („{n.text}“) byla zahozena: citace „{n.citation}“ se v poptávce nevyskytuje."
            )
    return valid, warnings


def _validate_requirements(output: RequirementsOutput, request: str) -> list[str]:
    errors = []
    ids = [n.id for n in output.requirements]
    for id_ in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f"ID náležitosti {id_} je použito vícekrát.")
    valid, warnings = _partition_requirements(output, request)
    if not valid:
        errors.append("Žádná náležitost nemá citaci, která by byla doslova v poptávce. " + " ".join(warnings))
    return errors


def validate_evaluation(h: Evaluation, criteria: list[Criterion]) -> list[str]:
    errors = []
    # Scoring skips criteria without scores, so this validation must ensure
    # that every input criterion is evaluated exactly once.
    counts: dict[str, int] = {}
    for s in h.criteria:
        counts[s.id] = counts.get(s.id, 0) + 1
    known = {k.id for k in criteria}
    for k in criteria:
        count = counts.get(k.id, 0)
        if count == 0:
            errors.append(f"Chybí hodnocení kritéria {k.id}.")
        elif count > 1:
            errors.append(f"Kritérium {k.id} je hodnoceno {count}×, má být právě jednou.")
    for id_ in counts:
        if id_ not in known:
            errors.append(f"Neznámé kritérium {id_} (povolená: {', '.join(k.id for k in criteria)}).")
    for s in h.criteria:
        if not 1 <= s.score <= 10:
            errors.append(f"Skóre kritéria {s.id} je {_number(s.score)}, musí být 1–10.")
        elif abs(s.score * 2 - round(s.score * 2)) > 1e-9:
            errors.append(f"Skóre kritéria {s.id} je {_number(s.score)}, musí být násobek 0,5.")
    ids = [n.id for n in h.suggestions]
    for id_ in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f"ID návrhu {id_} je použito vícekrát.")
    for n in h.suggestions:
        if n.criterion not in known:
            errors.append(f"Návrh {n.id} odkazuje na neznámé kritérium {n.criterion}.")
    return errors


def validate_review(p: SuggestionReview, h: Evaluation) -> list[str]:
    errors = []
    counts: dict[str, int] = {}
    for r in p.decisions:
        counts[r.suggestion_id] = counts.get(r.suggestion_id, 0) + 1
    suggestions = [n.id for n in h.suggestions]
    for id_ in suggestions:
        count = counts.get(id_, 0)
        if count == 0:
            errors.append(f"Chybí rozhodnutí k návrhu {id_}.")
        elif count > 1:
            errors.append(f"K návrhu {id_} je {count} rozhodnutí, má být právě jedno.")
    for id_ in counts:
        if id_ not in suggestions:
            errors.append(f"Rozhodnutí k neznámému návrhu {id_}.")
    return errors


def accepted_decisions(review: SuggestionReview) -> list[SuggestionDecision]:
    return [r for r in review.decisions if r.decision in ('accepted', 'partial')]


def _without_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(z for z in decomposed if not unicodedata.combining(z)).lower()


def validate_revision(old: str, new: str, evaluation: Evaluation, review: SuggestionReview) -> list[str]:
    if not new.strip():
        return ["Nový dokument je prázdný."]
    errors = []
    new_lines = {r.rstrip() for r in new.splitlines()}
    for line in old.splitlines():
        if line.startswith("# ") and line.rstrip() not in new_lines:
            errors.append(f"Z dokumentu zmizel nadpis „{line.rstrip()}“.")
    if len(new) < MIN_LENGTH_RATIO * len(old):
        by_id = {n.id: n for n in evaluation.suggestions}
        texts = []
        for r in accepted_decisions(review):
            n = by_id.get(r.suggestion_id)
            texts.append(_without_accents((n.suggestion if n else "") + " " + r.implementation))
        if not any(word in t for t in texts for word in SHORTENING_WORDS):
            errors.append(
                f"Dokument se zkrátil na {round(100 * len(new) / len(old))} % původní délky, "
                "ačkoli žádný přijatý návrh zkrácení nepožaduje. Vrať celý dokument."
            )
    return errors


# ---------------------------------------------------------------- steps

def extract_requirements(model: Model, sources: Sources) -> tuple[list[Requirement], list[str]]:
    instructions = render_prompt(sources.prompts, 'requirements', request=sources.request)
    effort = sources.configuration.settings.models.claude.extraction_effort
    output = with_repair(
        model,
        REQUIREMENTS_TASK,
        lambda z: model.json(instructions, z, RequirementsOutput, step='requirements', effort=effort),
        lambda v: _validate_requirements(v, sources.request),
        lambda v: v.model_dump_json(indent=2),
    )
    return _partition_requirements(output, sources.request)


def write_draft(model: Model, sources: Sources, requirements: list[Requirement]) -> str:
    configuration = sources.configuration
    instructions = render_prompt(
        sources.prompts, 'draft',
        document_type=configuration.profile.document_type,
        structure_instructions=configuration.profile.structure_instructions,
        requirements=_requirements_text(requirements),
        criteria=criteria_text(build_criteria(requirements, configuration.profile_criteria)),
        **common_variables(sources),
    )
    return with_repair(
        model,
        DRAFT_TASK,
        lambda z: _clean_document(model.text(instructions, z, step='draft_1')),
        lambda t: [] if t.strip() else ["Dokument je prázdný."],
        lambda t: t,
    )


def evaluate(
    model: Model,
    sources: Sources,
    criteria: list[Criterion],
    document: str,
    rejected_suggestions: list[tuple[RevisionSuggestion, SuggestionDecision]],
    step: str,
) -> tuple[Evaluation, list[str]]:
    configuration = sources.configuration
    max_suggestions = configuration.settings.loop.max_suggestions
    instructions = render_prompt(
        sources.prompts, 'evaluation',
        document_type=configuration.profile.document_type,
        criteria=criteria_text(criteria),
        max_suggestions=str(max_suggestions),
        rejected_suggestions=_rejected_text(rejected_suggestions),
        **common_variables(sources),
    )
    h = with_repair(
        model,
        document_section(document),
        lambda z: model.json(instructions, z, Evaluation, step=step),
        lambda v: validate_evaluation(v, criteria),
        lambda v: v.model_dump_json(indent=2),
    )
    warnings = []
    if len(h.suggestions) > max_suggestions:
        sorted_suggestions = sorted(h.suggestions, key=lambda n: PRIORITY_ORDER[n.priority])
        kept, omitted = sorted_suggestions[:max_suggestions], sorted_suggestions[max_suggestions:]
        warnings.append(
            f"Hodnotitel vrátil {len(h.suggestions)} návrhů, ponecháno {max_suggestions} podle priority; "
            f"vynechány: {', '.join(n.id for n in omitted)}."
        )
        h = h.model_copy(update={'suggestions': kept})
    return h, warnings


def review_suggestions(
    model: Model,
    sources: Sources,
    requirements: list[Requirement],
    document: str,
    evaluation: Evaluation,
    step: str,
) -> SuggestionReview:
    instructions = render_prompt(
        sources.prompts, 'review', requirements=_requirements_text(requirements), **common_variables(sources)
    )
    task = f"{document_section(document)}\n\n## Návrhy hodnotitele\n\n{_suggestions_text(evaluation.suggestions)}"
    return with_repair(
        model,
        task,
        lambda z: model.json(instructions, z, SuggestionReview, step=step),
        lambda v: validate_review(v, evaluation),
        lambda v: v.model_dump_json(indent=2),
    )


def incorporate_suggestions(
    model: Model,
    sources: Sources,
    requirements: list[Requirement],
    document: str,
    evaluation: Evaluation,
    review: SuggestionReview,
    step: str,
) -> str:
    instructions = render_prompt(
        sources.prompts, 'revision', requirements=_requirements_text(requirements), **common_variables(sources)
    )
    task = (
        f"{document_section(document)}\n\n## Přijaté návrhy k zapracování\n\n"
        f"{_accepted_text(evaluation, review)}"
    )
    return with_repair(
        model,
        task,
        lambda z: _clean_document(model.text(instructions, z, step=step)),
        lambda t: validate_revision(document, t, evaluation, review),
        lambda t: t,
    )

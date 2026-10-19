"""Compare a completed run against a manually refined reference (design section 11).

Only the evaluator sees the reference. Reports and JSON are replaced on repeated
comparison; the questionnaire is created only once to preserve consultant answers."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal, TypeVar

from jinja2 import Environment, FileSystemLoader
from pydantic import AliasChoices, BaseModel, Field, field_validator

from refiner.legacy import BETTER_VALUES, COVERAGE_STATUSES, VERDICTS

from refiner.artifacts import COMPARISON_FILE, COMPARISON_FORM
from refiner.run import Run
from refiner.data import (
    Evaluation,
    Criterion,
    CriterionScore,
    ScoreResult,
    RequirementsOutput,
    build_criteria,
)
from refiner.steps import (
    Sources,
    evaluate,
    with_repair,
    document_section,
    common_variables,
    criteria_text,
    render_prompt,
)
from refiner.models.interface import Model
from refiner.scoring import format_score, calculate_score
from refiner.input import SUPPORTED_EXTENSIONS, InputError, read_as_markdown, find_inputs

TEMPLATES = Path(__file__).parent / "output" / "templates"

COMPARISON_PROMPTS = ('comparison_criteria', 'comparison_elements', 'comparison_coverage')
FORM_QUESTIONS = (
    "Odeslal bych to po doplnění placeholderů?",
    "Kolik minut práce do odeslatelné verze?",
    "Věcné chyby?",
    "Co chybí?",
    "Co je lepší než v referenci?",
)

ELEMENTS_TASK = "Vypiš obsahové prvky dokumentu níže podle pokynů."
COVERAGE_ORDER = {'missing': 0, 'partial': 1, 'present': 2}
VERDICT_LABELS = {"generated": "lepší generovaná", "reference": "lepší reference", "tie": "nerozhodně"}
COVERAGE_LABELS = {"present": "je", "partial": "částečně", "missing": "chybí"}

Verdict = Literal['generated', "reference", 'tie']
T = TypeVar("T", bound=BaseModel)


# ---------------------------------------------------------------- structured model schemas

class CriterionComparison(BaseModel):
    id: str
    better: Literal["A", "B", "tie"] = Field(validation_alias=AliasChoices('better', 'lepsi'))
    rationale: str = Field(validation_alias=AliasChoices('rationale', 'zduvodneni'))

    @field_validator("better", mode="before")
    @classmethod
    def _normalize_better(cls, value):
        return BETTER_VALUES.get(value, value) if isinstance(value, str) else value


class PairComparison(BaseModel):
    criteria: list[CriterionComparison] = Field(validation_alias=AliasChoices('criteria', 'kriteria'))


class ReferenceElement(BaseModel):
    id: str
    description: str = Field(validation_alias=AliasChoices('description', 'popis'))


class ReferenceElements(BaseModel):
    elements: list[ReferenceElement] = Field(validation_alias=AliasChoices('elements', 'prvky'))


class ElementCoverage(BaseModel):
    id: str
    status: Literal["present", "partial", "missing"] = Field(validation_alias=AliasChoices('status', 'stav'))
    comment: str = Field(validation_alias=AliasChoices('comment', 'komentar'))

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value):
        return COVERAGE_STATUSES.get(value, value) if isinstance(value, str) else value


class Coverage(BaseModel):
    items: list[ElementCoverage] = Field(validation_alias=AliasChoices('items', 'polozky'))


class ComparisonResult(BaseModel):
    reference_score: ScoreResult = Field(validation_alias=AliasChoices('reference_score', 'skore_reference'))
    generated_score: ScoreResult = Field(validation_alias=AliasChoices('generated_score', 'skore_generovane'))
    comparison: dict[str, Verdict] = Field(validation_alias=AliasChoices('comparison', 'srovnani'))
    rationales: dict[str, list[str]] = Field(validation_alias=AliasChoices('rationales', 'zduvodneni'))
    elements: list[ReferenceElement] = Field(validation_alias=AliasChoices('elements', 'prvky'))
    coverage: list[ElementCoverage] = Field(validation_alias=AliasChoices('coverage', 'pokryti'))

    @field_validator("comparison", mode="before")
    @classmethod
    def _normalize_verdicts(cls, value):
        if not isinstance(value, dict):
            return value
        return {key: VERDICTS.get(verdict, verdict) if isinstance(verdict, str) else verdict
                for key, verdict in value.items()}


# ---------------------------------------------------------------- pure functions

_S1: dict[str, Verdict | None] = {"A": 'generated', "B": "reference", 'tie': None}
_S2: dict[str, Verdict | None] = {"A": "reference", "B": 'generated', 'tie': None}


def combine_comparisons(first: PairComparison, second: PairComparison) -> dict[str, Verdict]:
    """First order: A = generated, B = reference; second order reverses them. Disagreement ties."""
    second_by_id = {x.id: _S2[x.better] for x in second.criteria}
    result: dict[str, Verdict] = {}
    for x in first.criteria:
        first_verdict = _S1[x.better]
        result[x.id] = first_verdict if first_verdict is not None and first_verdict == second_by_id.get(x.id) else 'tie'
    return result


def find_reference(root: Path) -> Path:
    """Require a single supported reference file under root/examples/."""
    directory = Path(root) / "examples"
    files = find_inputs(directory) if directory.is_dir() else []
    if len(files) == 1:
        return files[0]
    raise InputError(
        f"Ve složce examples/ má být právě jedna referenční nabídka (DOCX, MD nebo TXT), "
        f"nalezeno: {len(files)}. Jinak použijte --reference SOUBOR."
    )


def read_reference(path: Path) -> str:
    path = Path(path)
    if not path.is_file():
        raise InputError(f"Referenční soubor {path} neexistuje.")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise InputError(f"Referenční soubor {path.name} musí být DOCX, MD nebo TXT.")
    return read_as_markdown(path)


# ---------------------------------------------------------------- response validation

def _counts(ids: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for i in ids:
        counts[i] = counts.get(i, 0) + 1
    return counts


def _exactly_once(ids: list[str], expected: list[str], subject: str) -> list[str]:
    counts = _counts(ids)
    errors = []
    for id_ in expected:
        count = counts.get(id_, 0)
        if count == 0:
            errors.append(f"Chybí {subject} {id_}.")
        elif count > 1:
            errors.append(f"{subject[:1].upper()}{subject[1:]} {id_} je uvedeno {count}×, má být právě jednou.")
    for id_ in counts:
        if id_ not in expected:
            errors.append(f"Neznámé ID {id_} (povolená: {', '.join(expected)}).")
    return errors


def validate_comparison(s: PairComparison, criteria: list[Criterion]) -> list[str]:
    return _exactly_once([x.id for x in s.criteria], [k.id for k in criteria], "srovnání kritéria")


def validate_elements(s: ReferenceElements) -> list[str]:
    if not s.elements:
        return ["Seznam prvků je prázdný."]
    ids = [p.id for p in s.elements]
    return [f"ID prvku {i} je použito vícekrát." for i in sorted({i for i in ids if ids.count(i) > 1})]


def validate_coverage(p: Coverage, elements: list[ReferenceElement]) -> list[str]:
    return _exactly_once([x.id for x in p.items], [x.id for x in elements], "pokrytí prvku")


# ---------------------------------------------------------------- model tasks

def _comparison_task(a: str, b: str) -> str:
    return (f"## Dokument A\n\n<dokument_a>\n{a}\n</dokument_a>\n\n"
            f"## Dokument B\n\n<dokument_b>\n{b}\n</dokument_b>")


def _elements_text(elements: list[ReferenceElement]) -> str:
    return "\n".join(f"- **{p.id}** {p.description}" for p in elements)


BETTER_LABELS = {"A": "lepší A", "B": "lepší B", 'tie': "stejné"}


def _rationales(first: PairComparison, second: PairComparison) -> dict[str, list[str]]:
    """Rationales from both comparisons, annotated with the identity of A and B."""
    result: dict[str, list[str]] = {}
    for name, s in (("Srovnání 1 (A = generovaná, B = reference)", first),
                     ("Srovnání 2 (A = reference, B = generovaná)", second)):
        for x in s.criteria:
            result.setdefault(x.id, []).append(f"{name}, {BETTER_LABELS[x.better]}: {x.rationale}")
    return result


# ---------------------------------------------------------------- reports

def _form(run: Run, reference_name: str | None) -> str:
    rows = [
        "# Porovnání s referencí – hodnocení konzultanta",
        "",
        f"Běh: {run.directory.name} · finální verze: {run.state.final_version}"
        + (f" · reference: {reference_name}" if reference_name else ""),
        "",
        "Vyplňte po přečtení finálního dokumentu a porovnání s referencí. "
        "Tohle je skutečné měřítko úspěchu; automatické části porovnání slouží k ladění.",
    ]
    for i, question in enumerate(FORM_QUESTIONS, start=1):
        rows += ["", f"## {i}. {question}", "", "Odpověď:"]
    return "\n".join(rows) + "\n"


def _calibration_sentence(score: ScoreResult, target: float) -> str:
    target_text, total = format_score(target), format_score(score.total)
    if score.target_met:
        return f"Reference dosáhla cílového skóre {target_text} (skóre {total}). Práh je pro tohoto hodnotitele dosažitelný."
    return (
        f"Reference nedosáhla cílového skóre {target_text} (skóre {total}; {'; '.join(score.unmet_reasons)}). "
        "Když ručně dotažená nabídka práh nesplní, je práh pro tohoto hodnotitele nereálný, "
        "nebo kritéria měří něco jiného, než chceme."
    )


def _html(run: Run, sources: Sources, criteria: list[Criterion], v: ComparisonResult,
          calibration: Evaluation, reference_name: str | None) -> str:
    final_version = run.state.final_version
    key = f"evaluation_{final_version}"
    generated_evaluation = run.data(key, Evaluation) if run.is_done(key) and run.state.steps[key].data else None
    ref = {s.id: s for s in calibration.criteria}
    gen = {s.id: s for s in generated_evaluation.criteria} if generated_evaluation else {}

    def number(s: CriterionScore | None) -> str:
        return format_score(s.score) if s is not None else "–"

    calibration_rows = [
        {"id": k.id, 'name': k.name, "reference": number(ref.get(k.id)),
         'generated': number(gen.get(k.id)), 'rationales': ref[k.id].rationale if k.id in ref else ""}
        for k in criteria
    ]
    summary = [
        {'name': name, "reference": format_score(getattr(v.reference_score, a)),
         'generated': format_score(getattr(v.generated_score, a))}
        for a, name in (("a", "Skupina A – náležitosti"), ("b", "Skupina B – obecná kvalita"),
                         ("c", "Skupina C – bez vymyšlených faktů"), ("total", "Celkem"))
    ]
    comparisons = [
        {"id": k.id, 'name': k.name, 'verdict': v.comparison.get(k.id, 'tie'),
         'rationales': v.rationales.get(k.id, [])}
        for k in criteria
    ]
    counts = {d: sum(1 for r in comparisons if r['verdict'] == d) for d in ('generated', 'reference', 'tie')}
    descriptions = {p.id: p.description for p in v.elements}
    coverage = sorted(
        ({"id": p.id, 'description': descriptions.get(p.id, ""), 'status': p.status, 'comment': p.comment} for p in v.coverage),
        key=lambda r: COVERAGE_ORDER[r['status']],
    )
    coverage_counts = {s: sum(1 for r in coverage if r['status'] == s) for s in COVERAGE_ORDER}

    final_name = f"FINALNI_{sources.configuration.output_profile_name}.md"
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True)
    return env.get_template("comparison.html.j2").render(
        directory=run.directory.name, reference=reference_name, final_version=final_version,
        final_file=final_name if (run.directory / final_name).exists() else None,
        sentence=_calibration_sentence(v.reference_score, sources.configuration.settings.loop.target_score),
        target_met=v.reference_score.target_met,
        fabricated_facts=len(calibration.fabricated_facts),
        calibration=calibration_rows, summary=summary, comparisons=comparisons, counts=counts,
        coverage=coverage, coverage_counts=coverage_counts, form=COMPARISON_FORM,
        verdict_labels=VERDICT_LABELS, coverage_labels=COVERAGE_LABELS,
    )


# ---------------------------------------------------------------- comparison

def compare(
    run: Run,
    sources: Sources,
    reference_md: str,
    evaluator: Model,
    report: Callable[[str], None],
    *,
    reference_name: str | None = None,
) -> Path:
    """Make five evaluator calls and write Czech comparison reports.

    Completion state stays unchanged; usage is added even on failure."""
    final_version = run.state.final_version
    if run.state.status != 'completed' or final_version is None:
        raise InputError(f"Běh {run.directory.name} není dokončený; porovnat lze jen dokončený běh.")
    if str(final_version) not in run.state.scores or not run.is_done(f"draft_{final_version}"):
        raise InputError(f"Běh {run.directory.name} nemá uloženou finální verzi {final_version} nebo její skóre.")

    configuration = sources.configuration
    requirements = run.data('requirements', RequirementsOutput).requirements
    criteria = build_criteria(requirements, configuration.profile_criteria)
    generated = run.text(f"draft_{final_version}")
    generated_score = run.state.scores[str(final_version)]

    # Render all prompts before calling a model so missing files consume no tokens.
    variables = {**common_variables(sources), "document_type": configuration.profile.document_type,
                'criteria': criteria_text(criteria)}
    instructions = {n: render_prompt(sources.prompts, n, **variables) for n in COMPARISON_PROMPTS}

    def json_with_repair(schema: type[T], step: str, instructions: str, task: str,
                       validate: Callable[[T], list[str]]) -> T:
        """Validate with at most one repair, matching the regular document loop."""
        return with_repair(
            evaluator, task,
            lambda z: evaluator.json(instructions, z, schema, step=step),
            validate,
            lambda x: x.model_dump_json(indent=2),
        )

    try:
        report("[1/5] Kalibrace: hodnocení reference stejnými kritérii…")
        calibration, _ = evaluate(evaluator, sources, criteria, reference_md, [], step='comparison_calibration')
        reference_score = calculate_score(calibration, criteria, configuration.settings)
        report(f"hotovo, skóre reference {format_score(reference_score.total)} "
                f"(finální verze {format_score(generated_score.total)})")

        def validate_pair(s: PairComparison) -> list[str]:
            return validate_comparison(s, criteria)

        report("[2/5] Párové srovnání po kritériích…")
        first = json_with_repair(PairComparison, 'comparison_pair_1', instructions['comparison_criteria'],
                            _comparison_task(generated, reference_md), validate_pair)
        report("hotovo")
        report("[3/5] Párové srovnání s prohozeným pořadím…")
        second = json_with_repair(PairComparison, 'comparison_pair_2', instructions['comparison_criteria'],
                            _comparison_task(reference_md, generated), validate_pair)
        report("hotovo")

        report("[4/5] Obsahové prvky reference…")
        elements = json_with_repair(ReferenceElements, 'comparison_elements', instructions['comparison_elements'],
                               f"{ELEMENTS_TASK}\n\n{document_section(reference_md)}", validate_elements).elements
        report(f"hotovo, počet prvků: {len(elements)}")

        report("[5/5] Pokrytí prvků v generované nabídce…")
        coverage = json_with_repair(
            Coverage, 'comparison_coverage', instructions['comparison_coverage'],
            f"{document_section(generated)}\n\n## Prvky k ověření\n\n{_elements_text(elements)}",
            lambda p: validate_coverage(p, elements),
        ).items
        report("hotovo")
    finally:
        usage = evaluator.take_usage()
        if usage:
            run.add_usage(usage)

    result = ComparisonResult(
        reference_score=reference_score,
        generated_score=generated_score,
        comparison=combine_comparisons(first, second),
        rationales=_rationales(first, second),
        elements=elements,
        coverage=coverage,
    )
    run.write_fixed("data/porovnani.json", result.model_dump_json(indent=2))
    run.write_fixed("data/porovnani_kalibrace.json", calibration.model_dump_json(indent=2))
    if not (run.directory / COMPARISON_FORM).exists():
        run.write_fixed(COMPARISON_FORM, _form(run, reference_name))
    return run.write_fixed(
        COMPARISON_FILE, _html(run, sources, criteria, result, calibration, reference_name))

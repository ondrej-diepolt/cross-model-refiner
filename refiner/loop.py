"""Resumable draft, evaluation, review, and revision loop (design section 3.3)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from refiner.run import Run
from refiner.data import (
    Evaluation,
    RevisionSuggestion,
    SuggestionReview,
    SuggestionDecision,
    ScoreResult,
    RequirementsOutput,
    build_criteria,
)
from refiner.steps import (
    Sources,
    extract_requirements,
    write_draft,
    evaluate,
    review_suggestions,
    accepted_decisions,
    incorporate_suggestions,
)
from refiner.models.interface import Model
from refiner.scoring import format_score, calculate_score, select_final_version
from refiner.output.diff import diff_html
from refiner.output.markdown import evaluation_markdown, requirements_markdown, review_markdown

StopReason = Literal['target_reached', 'revision_limit', 'no_changes']


@dataclass
class RunResult:
    reason: StopReason
    final_version: int
    scores: dict[int, ScoreResult]   # key = evaluation number = evaluated version number


def _rejected(h: Evaluation, p: SuggestionReview) -> list[tuple[RevisionSuggestion, SuggestionDecision]]:
    """Rejected suggestions from one round; suggestion IDs are local to each evaluation."""
    by_id = {n.id: n for n in h.suggestions}
    return [
        (by_id[r.suggestion_id], r)
        for r in p.decisions
        if r.decision == 'rejected' and r.suggestion_id in by_id
    ]


def run_loop(
    run: Run,
    sources: Sources,
    writer: Model,
    evaluator: Model,
    report: Callable[[str], None],
) -> RunResult:
    """Load completed steps from disk instead of calling models. Exceptions propagate."""
    settings = sources.configuration.settings
    max_revisions = settings.loop.max_revisions
    total_steps = 2 + 3 * max_revisions + 1

    def announce(position: int, description: str) -> None:
        report(f"[{position}/{total_steps}] {description}…")

    def save_usage() -> None:
        run.add_usage(writer.take_usage() + evaluator.take_usage())

    # Step 0: requirements
    if run.is_done('requirements'):
        requirements = run.data('requirements', RequirementsOutput).requirements
    else:
        announce(1, "Náležitosti z poptávky")
        requirements, warnings = extract_requirements(writer, sources)
        run.write('requirements', "nalezitosti.md", requirements_markdown(requirements, warnings),
                  data=RequirementsOutput(requirements=requirements))
        for v in warnings:
            run.add_warning(v)
        save_usage()
    criteria = build_criteria(requirements, sources.configuration.profile_criteria)

    # Step 1: draft v1
    if run.is_done('draft_1'):
        document = run.text('draft_1')
    else:
        announce(2, "Návrh v1")
        document = write_draft(writer, sources, requirements)
        run.write('draft_1', "navrh_v1.md", document)
        save_usage()

    scores: dict[int, ScoreResult] = {}
    rejected_suggestions: list[tuple[RevisionSuggestion, SuggestionDecision]] = []

    def finish(reason: StopReason) -> RunResult:
        final = select_final_version(scores)
        return RunResult(reason=reason, final_version=final, scores=dict(scores))

    k = 1
    while True:
        position = 3 + 3 * (k - 1)
        is_final = k == max_revisions + 1

        # Evaluation k (version k)
        step = f"evaluation_{k}"
        if run.is_done(step):
            h = run.data(step, Evaluation)
            result = run.state.scores.get(str(k))
            if result is None:   # interrupted between writing the evaluation and saving its score
                result = calculate_score(h, criteria, settings)
                run.save_score(k, result)
        else:
            announce(position, f"Hodnocení {k}" + (" (závěrečné)" if is_final else ""))
            h, warnings = evaluate(evaluator, sources, criteria, document, rejected_suggestions, step)
            result = calculate_score(h, criteria, settings)
            run.write(step, f"hodnoceni_{k}.md", evaluation_markdown(k, h, result, criteria), data=h)
            run.save_score(k, result)
            for v in warnings:
                run.add_warning(v)
            save_usage()
            report(f"hotovo, skóre {format_score(result.total)}")
        scores[k] = result

        if result.target_met:
            return finish('target_reached')
        if is_final:
            return finish('revision_limit')

        # Review k
        step = f"review_{k}"
        if run.is_done(step):
            p = run.data(step, SuggestionReview)
        else:
            announce(position + 1, f"Posouzení návrhů z hodnocení {k}")
            p = review_suggestions(writer, sources, requirements, document, h, step)
            run.write(step, f"posouzeni_{k}.md", review_markdown(k, h, p), data=p)
            save_usage()
        rejected_suggestions += _rejected(h, p)

        if not accepted_decisions(p):
            return finish('no_changes')

        # Revision k -> version k+1
        step = f"draft_{k + 1}"
        if run.is_done(step):
            document = run.text(step)
        else:
            announce(position + 2, f"Zapracování přijatých návrhů → v{k + 1}")
            new = incorporate_suggestions(writer, sources, requirements, document, h, p, step)
            run.write(step, f"navrh_v{k + 1}.md", new)
            run.write_for_step(step, f"navrh_v{k + 1}_zmeny.html",
                        diff_html(document, new, f"Verze {k}", f"Verze {k + 1}"))
            save_usage()
            document = new
        k += 1

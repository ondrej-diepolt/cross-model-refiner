import pytest

from refiner.run import Run
from refiner.models.errors import ModelError
from refiner.models.fakes import FakeModel
from refiner.loop import run_loop
from tests.helpers import (
    make_run,
    make_evaluation,
    scripted_responses,
    make_review,
    scripted_models,
    draft_text,
)


def _steps(model: FakeModel) -> list[str]:
    return [k for k, *_ in model.calls]


def _silent(_: str) -> None:
    pass


def test_target_reached_in_first_evaluation(tmp_path, sources):
    run = make_run(tmp_path, sources)
    v = run_loop(run, sources, *scripted_models([9.5]), report=_silent)
    assert v.reason == 'target_reached' and v.final_version == 1
    assert [p.name for p in sorted(run.directory.glob("0*"))] == [
        "01_poptavka.md", "02_nalezitosti.md", "03_navrh_v1.md", "04_hodnoceni_1.md"]
    assert list(v.scores) == [1] and v.scores[1].target_met and v.scores[1].total == 9.6
    assert run.state.scores["1"].total == v.scores[1].total


def test_target_reached_in_second_evaluation(tmp_path, sources):
    run = make_run(tmp_path, sources)
    writer, evaluator = scripted_models([7.0, 9.5])
    v = run_loop(run, sources, writer, evaluator, report=_silent)
    assert v.reason == 'target_reached' and v.final_version == 2
    assert _steps(evaluator) == ['evaluation_1', 'evaluation_2']
    assert _steps(writer) == ['requirements', 'draft_1', 'review_1', 'draft_2']
    assert run.text('draft_2') == draft_text(2)


def test_three_revisions_and_final_evaluation(tmp_path, sources):
    run = make_run(tmp_path, sources)
    writer, evaluator = scripted_models([7.0, 8.0, 8.5, 9.0])
    v = run_loop(run, sources, writer, evaluator, report=_silent)
    assert v.reason == 'revision_limit' and len(v.scores) == 4
    assert v.final_version == 4
    assert _steps(evaluator) == ['evaluation_1', 'evaluation_2', 'evaluation_3', 'evaluation_4']
    assert sum(1 for k in _steps(writer) if k.startswith("draft_")) == 4   # v1 + 3 revisions
    assert 'review_4' not in _steps(writer)
    assert (run.directory / "06_navrh_v2_zmeny.html").exists()
    assert set(run.state.scores) == {"1", "2", "3", "4"}


def test_no_accepted_suggestions_stops_before_next_evaluation(tmp_path, sources):
    run = make_run(tmp_path, sources)
    writer, evaluator = scripted_models([7.0, 9.5], decision='rejected')
    v = run_loop(run, sources, writer, evaluator, report=_silent)
    assert v.reason == 'no_changes' and v.final_version == 1
    assert _steps(evaluator) == ['evaluation_1']
    assert 'draft_2' not in _steps(writer)
    assert (run.directory / "05_posouzeni_1.md").exists()


def test_score_drop_selects_earlier_version(tmp_path, sources):
    run = make_run(tmp_path, sources)
    v = run_loop(run, sources, *scripted_models([7.0, 9.0, 8.0, 8.5]), report=_silent)
    assert v.reason == 'revision_limit'
    assert v.final_version == 2


def test_met_target_beats_higher_blocked_score(tmp_path, sources):
    """Version 2 has a higher score but fails a requirement minimum; version 3 meets the target."""
    run = make_run(tmp_path, sources)
    writer, evaluator = scripted_responses([7.0, 10.0, 9.5])
    h2 = make_evaluation(10.0, {"N1": 7.5})
    evaluator['evaluation_2'] = [h2]
    writer['review_2'] = [make_review(h2)]
    evaluator['evaluation_3'] = [make_evaluation(9.5, {"B1": 9.0})]
    v = run_loop(run, sources, FakeModel(writer, name="claude-falesny"),
                     FakeModel(evaluator, name="gpt-falesny"), report=_silent)
    assert not v.scores[2].target_met and v.scores[3].target_met
    assert v.scores[2].total > v.scores[3].total
    assert v.reason == 'target_reached' and v.final_version == 3


def _responses_with_mixed_review(scores: list[float]):
    """Round 1 partially accepts V1 and rejects V2 with recognizable text."""
    writer, evaluator = scripted_responses(scores)
    h1 = make_evaluation(scores[0])
    h1 = h1.model_copy(update={'suggestions': [
        h1.suggestions[0].model_copy(update={'suggestion': "Doplnit tabulku rizik."}),
        h1.suggestions[1].model_copy(update={'suggestion': "Přidat neexistující referenci ODMITNUTO-XYZ."}),
    ]})
    p1 = make_review(h1, 'partial')
    p1.decisions[1] = p1.decisions[1].model_copy(
        update={'decision': 'rejected', 'rationale': "Reference není ve zdrojích."})
    evaluator['evaluation_1'] = [h1]
    writer['review_1'] = [p1]
    return writer, evaluator


def test_rejected_suggestions_reach_next_evaluation(tmp_path, sources):
    run = make_run(tmp_path, sources)
    writer_responses, evaluator_responses = _responses_with_mixed_review([7.0, 9.5])
    writer, evaluator = FakeModel(writer_responses), FakeModel(evaluator_responses, name="gpt-falesny")
    v = run_loop(run, sources, writer, evaluator, report=_silent)
    assert v.reason == 'target_reached'
    instructions = {k: i for k, i, _ in evaluator.calls}
    assert "ODMITNUTO-XYZ" in instructions['evaluation_2']
    assert "Reference není ve zdrojích." in instructions['evaluation_2']
    assert "Doplnit tabulku rizik." not in instructions['evaluation_2']   # partially accepted is not rejected
    assert "ODMITNUTO-XYZ" not in instructions['evaluation_1']


def test_resume_does_not_repeat_completed_steps(tmp_path, sources):
    run = make_run(tmp_path, sources)
    writer_responses, evaluator_responses = scripted_responses([7.0, 8.0, 9.5])
    evaluator_responses['evaluation_2'] = [ModelError('overloaded', "OpenAI")]
    with pytest.raises(ModelError):
        run_loop(run, sources, FakeModel(writer_responses), FakeModel(evaluator_responses, name="gpt-falesny"),
                     report=_silent)

    reopened = Run.open(run.directory)
    h2 = make_evaluation(8.0)
    next_evaluator = FakeModel({'evaluation_2': [h2], 'evaluation_3': [make_evaluation(9.5)]}, name="gpt-falesny")
    next_writer = FakeModel({'review_2': [make_review(h2)], 'draft_3': [draft_text(3)]})
    v = run_loop(reopened, sources, next_writer, next_evaluator, report=_silent)

    assert v.reason == 'target_reached' and v.final_version == 3 and set(v.scores) == {1, 2, 3}
    assert all(not k.startswith(('requirements', 'draft_1', 'evaluation_1', 'review_1', 'draft_2'))
               for k in _steps(next_writer) + _steps(next_evaluator))
    assert [p.name for p in sorted(run.directory.glob("[0-9][0-9]_*"))] == [
        "01_poptavka.md", "02_nalezitosti.md", "03_navrh_v1.md", "04_hodnoceni_1.md",
        "05_posouzeni_1.md", "06_navrh_v2.md", "06_navrh_v2_zmeny.html", "07_hodnoceni_2.md",
        "08_posouzeni_2.md", "09_navrh_v3.md", "09_navrh_v3_zmeny.html", "10_hodnoceni_3.md"]
    assert reopened.state.steps['draft_1'].number == 3 and reopened.state.steps['evaluation_3'].number == 10


def test_resume_preserves_rejected_suggestions(tmp_path, sources):
    run = make_run(tmp_path, sources)
    writer_responses, evaluator_responses = _responses_with_mixed_review([7.0, 9.5])
    evaluator_responses['evaluation_2'] = [ModelError('overloaded', "OpenAI")]
    with pytest.raises(ModelError):
        run_loop(run, sources, FakeModel(writer_responses), FakeModel(evaluator_responses, name="gpt-falesny"),
                     report=_silent)

    next_evaluator = FakeModel({'evaluation_2': [make_evaluation(9.5)]}, name="gpt-falesny")
    v = run_loop(Run.open(run.directory), sources, FakeModel({}), next_evaluator, report=_silent)
    assert v.reason == 'target_reached'
    instructions = {k: i for k, i, _ in next_evaluator.calls}
    assert "ODMITNUTO-XYZ" in instructions['evaluation_2']


def test_usage_saved_after_each_step(tmp_path, sources):
    run = make_run(tmp_path, sources)
    writer_responses, evaluator_responses = scripted_responses([7.0, 9.5])
    evaluator_responses['evaluation_2'] = [ModelError('overloaded', "OpenAI")]
    with pytest.raises(ModelError):
        run_loop(run, sources, FakeModel(writer_responses), FakeModel(evaluator_responses, name="gpt-falesny"),
                     report=_silent)
    # Five successful calls: requirements, draft_1, evaluation_1, review_1, draft_2.
    # evaluation_2 failed before a response, so it has no usage.
    saved = Run.open(run.directory).state.usage
    assert [s.step for s in saved] == ['requirements', 'draft_1', 'evaluation_1', 'review_1', 'draft_2']


def test_script_rejects_invalid_score():
    with pytest.raises(ValueError, match="0,5"):
        scripted_models([9.8])


def test_progress_messages(tmp_path, sources):
    run = make_run(tmp_path, sources)
    messages: list[str] = []
    run_loop(run, sources, *scripted_models([7.0, 9.5]), report=messages.append)
    text = "\n".join(messages)
    assert "[1/12]" in text and "Hodnocení 1" in text and "skóre" in text
    assert "[3/12] Hodnocení 1" in text and "[6/12] Hodnocení 2" in text
    assert "hotovo, skóre 7,5" in text   # 0,5·7 + 0,35·7 + 0,15·10 = 7,45 → 7,5

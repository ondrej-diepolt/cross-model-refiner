import pytest

from refiner.data import Evaluation, RevisionSuggestion, SuggestionReview, SuggestionDecision, Requirement
from refiner.configuration import ConfigurationError
from refiner.steps import (
    extract_requirements,
    write_draft,
    evaluate,
    review_suggestions,
    accepted_decisions,
    render_prompt,
    incorporate_suggestions,
    validate_evaluation,
    validate_review,
    validate_revision,
)
from refiner.models.errors import ModelError
from refiner.models.fakes import FakeModel
from tests.helpers import make_evaluation, make_criteria, make_review

VARIABLES = {
    'requirements': ['request'],
    'draft': ["document_type", "structure_instructions", 'request', 'materials', 'requirements', 'criteria'],
    'evaluation': ["document_type", 'request', 'materials', 'criteria', "max_suggestions", "rejected_suggestions"],
    'review': ['request', 'materials', 'requirements'],
    'revision': ['request', 'materials', 'requirements'],
}

REQUIREMENTS = [
    Requirement(id="N1", text="Metodika", citation="popis metodiky cvičení"),
    Requirement(id="N2", text="Harmonogram", citation="harmonogram a hlavní milníky realizace"),
    Requirement(id="N3", text="Cena", citation="cenu za celé plnění"),
]


def _suggestion(id_: str, priority: str = 'medium', text: str = "Nové znění.") -> RevisionSuggestion:
    return RevisionSuggestion(id=id_, criterion="B1", location="kap. 1", problem="Problém.", suggestion=text, priority=priority)


def _decision(id_: str, decision: str, implementation: str = "Takto.", rationale: str = "Zdůvodnění.") -> SuggestionDecision:
    return SuggestionDecision(suggestion_id=id_, support="Opora.", assumption="Předpoklad.", consequence="Důsledek.",
                      decision=decision, rationale=rationale, implementation=implementation)


# ---------------------------------------------------------------- prompts

def test_all_prompts_render(repo_root):
    for name, variables in VARIABLES.items():
        values = {p: f"«{p.upper()}»" for p in variables}
        text = render_prompt(repo_root / 'prompts', name, **values)
        assert "${" not in text, name
        for p, h in values.items():
            assert h in text, f"{name}.md does not use variable {p}"


def test_missing_prompt_variable(tmp_path):
    (tmp_path / "pokus.md").write_text("Ahoj ${jmeno} a ${neznama}.", encoding="utf-8")
    with pytest.raises(ConfigurationError) as e:
        render_prompt(tmp_path, "pokus", jmeno="Petr")
    assert "pokus.md" in str(e.value) and "neznama" in str(e.value)


def test_prompt_with_literal_dollar_renders(tmp_path):
    (tmp_path / "pokus.md").write_text("Cena $$100 pro ${jmeno}.", encoding="utf-8")
    assert render_prompt(tmp_path, "pokus", jmeno="Petr") == "Cena $100 pro Petr."


# ---------------------------------------------------------------- requirements

def test_requirements_discard_fabricated_citation(sources):
    m = FakeModel({'requirements': [{'requirements': [
        {"id": "N1", "text": "Harmonogram", 'citation': "harmonogram a hlavní milníky realizace"},
        {"id": "N2", "text": "Pojištění", 'citation': "doklad o pojištění odpovědnosti"}]}]})
    n, var = extract_requirements(m, sources)
    assert [x.id for x in n] == ["N1"] and "N2" in var[0]
    assert len(m.calls) == 1


def test_requirement_citation_normalizes_whitespace(sources):
    m = FakeModel({'requirements': [{'requirements': [
        {"id": "N1", "text": "Harmonogram", 'citation': "harmonogram  a hlavní\nmilníky realizace"}]}]})
    n, var = extract_requirements(m, sources)
    assert [x.id for x in n] == ["N1"] and var == []


def test_no_valid_requirement_after_repair(sources):
    invalid = {'requirements': [{"id": "N1", "text": "X", 'citation': "vymyšlená věta"}]}
    m = FakeModel({'requirements': [invalid, invalid]})
    with pytest.raises(ModelError) as e:
        extract_requirements(m, sources)
    assert e.value.kind == 'invalid_output' and e.value.service == "Anthropic"
    assert len(m.calls) == 2 and "## Oprava" in m.calls[1][2]


def test_requirements_use_extraction_effort(sources):
    class RecordingModel(FakeModel):
        def json(self, instructions, task, schema, *, step, effort=None):
            self.effort = effort
            return super().json(instructions, task, schema, step=step, effort=effort)

    m = RecordingModel({'requirements': [{'requirements': [
        {"id": "N1", "text": "Harmonogram", 'citation': "harmonogram a hlavní milníky realizace"}]}]})
    extract_requirements(m, sources)
    assert m.effort == "medium"
    assert "harmonogram a hlavní milníky realizace" in m.calls[0][1]


# ---------------------------------------------------------------- draft

def test_draft_receives_sources_and_missing_materials_instruction(sources):
    m = FakeModel({'draft': ["# Nabídka\n\nText."]})
    assert write_draft(m, sources, REQUIREMENTS) == "# Nabídka\n\nText."
    step, instructions, _ = m.calls[0]
    assert step == 'draft_1'
    assert "harmonogram a hlavní milníky realizace" in instructions
    assert "Profil firmy nebyl dodán" in instructions
    assert "B1" in instructions and "N3" in instructions


# ---------------------------------------------------------------- evaluation

def test_evaluation_repairs_missing_criterion(sources):
    criteria = make_criteria()
    without_b3 = make_evaluation(8, criteria=[k for k in criteria if k.id != "B3"])
    m = FakeModel({'evaluation': [without_b3, make_evaluation(8)]}, name="gpt-6-astra")
    h, var = evaluate(m, sources, criteria, "# Dokument", [], 'evaluation_1')
    assert {s.id for s in h.criteria} == {k.id for k in criteria} and var == []
    assert len(m.calls) == 2
    second_task = m.calls[1][2]
    assert "## Oprava" in second_task and "B3" in second_task
    assert "## Dokument" in m.calls[0][2] and "## Oprava" not in m.calls[0][2]


def test_evaluation_repairs_invalid_model_output(sources):
    error = ModelError('invalid_output', "OpenAI", detail="neplatný JSON", raw_response="{")
    m = FakeModel({'evaluation': [error, make_evaluation(8)]}, name="gpt-6-astra")
    h, _ = evaluate(m, sources, make_criteria(), "# Dokument", [], 'evaluation_1')
    assert len(m.calls) == 2 and "neplatný JSON" in m.calls[1][2]


def test_evaluation_does_not_retry_other_model_errors(sources):
    m = FakeModel({'evaluation': [ModelError('overloaded', "OpenAI"), make_evaluation(8)]}, name="gpt-6-astra")
    with pytest.raises(ModelError) as e:
        evaluate(m, sources, make_criteria(), "# Dokument", [], 'evaluation_1')
    assert e.value.kind == 'overloaded' and len(m.calls) == 1


def test_evaluation_second_failure_preserves_raw_response(sources):
    criteria = make_criteria()
    without_b3 = make_evaluation(8, criteria=[k for k in criteria if k.id != "B3"])
    m = FakeModel({'evaluation': [without_b3, without_b3]}, name="gpt-6-astra")
    with pytest.raises(ModelError) as e:
        evaluate(m, sources, criteria, "# Dokument", [], 'evaluation_1')
    assert e.value.kind == 'invalid_output' and e.value.service == "OpenAI"
    assert "B3" in e.value.detail
    assert e.value.raw_response and Evaluation.model_validate_json(e.value.raw_response) == without_b3


def test_valid_evaluation():
    assert validate_evaluation(make_evaluation(8, {"B2": 7.5, "N1": 10, "N2": 1}), make_criteria()) == []


def test_evaluation_score_outside_range():
    errors = validate_evaluation(make_evaluation(8, {"N1": 11}), make_criteria())
    assert errors != [] and "N1" in errors[0]


def test_evaluation_score_requires_half_steps():
    errors = validate_evaluation(make_evaluation(8, {"B2": 7.3}), make_criteria())
    assert errors != [] and "B2" in errors[0]


def test_evaluation_extra_and_duplicate_criteria():
    h = make_evaluation(8)
    h.criteria.append(h.criteria[0].model_copy(update={"id": "X9"}))
    h.criteria.append(h.criteria[1].model_copy())
    errors = " ".join(validate_evaluation(h, make_criteria()))
    assert "X9" in errors and h.criteria[1].id in errors


def test_evaluation_duplicate_suggestion_ids_and_unknown_criterion():
    h = make_evaluation(8)
    h.suggestions = [_suggestion("H1"), _suggestion("H1"), _suggestion("H2").model_copy(update={'criterion': "Z7"})]
    errors = " ".join(validate_evaluation(h, make_criteria()))
    assert "H1" in errors and "Z7" in errors


def test_evaluation_trims_suggestions_by_priority(sources):
    priority = ['low', 'medium'] * 4 + ['high', 'low', 'high', 'high']
    h = make_evaluation(8)
    h.suggestions = [_suggestion(f"H{i}", p) for i, p in enumerate(priority, start=1)]
    m = FakeModel({'evaluation': [h]}, name="gpt-6-astra")
    result, var = evaluate(m, sources, make_criteria(), "# Dokument", [], 'evaluation_1')
    ids = [n.id for n in result.suggestions]
    assert len(ids) == 10
    assert {"H9", "H11", "H12"} <= set(ids)
    assert var and "12" in var[0]
    # The omitted suggestions are the last two low-priority items.
    assert set(n.id for n in h.suggestions) - set(ids) == {"H7", "H10"}


def test_rejected_suggestions_in_instructions(sources):
    rejected = [(_suggestion("H1-02", text="Přidat certifikaci ISO 27001."),
            _decision("H1-02", 'rejected', rationale="Certifikace není v podkladech."))]
    m = FakeModel({'evaluation': [make_evaluation(8)]}, name="gpt-6-astra")
    evaluate(m, sources, make_criteria(), "# Dokument", rejected, 'evaluation_2')
    instructions = m.calls[0][1]
    assert "Přidat certifikaci ISO 27001." in instructions
    assert "Certifikace není v podkladech." in instructions


def test_no_rejections_instruction(sources):
    m = FakeModel({'evaluation': [make_evaluation(8)]}, name="gpt-6-astra")
    evaluate(m, sources, make_criteria(), "# Dokument", [], 'evaluation_1')
    assert "(žádné)" in m.calls[0][1]


# ---------------------------------------------------------------- review

def test_review_missing_decision():
    h = make_evaluation(8, suggestions=3)
    p = make_review(h)
    p.decisions = p.decisions[:2]
    errors = validate_review(p, h)
    assert errors != [] and "V3" in " ".join(errors)


def test_review_unknown_and_duplicate_ids():
    h = make_evaluation(8, suggestions=2)
    p = make_review(h)
    p.decisions.append(_decision("V1", 'accepted'))
    p.decisions.append(_decision("V9", 'accepted'))
    errors = " ".join(validate_review(p, h))
    assert "V1" in errors and "V9" in errors
    assert validate_review(make_review(h), h) == []


def test_review_repairs_missing_decision(sources):
    h = make_evaluation(8, suggestions=3)
    incomplete = make_review(h)
    incomplete.decisions = incomplete.decisions[:2]
    m = FakeModel({'review': [incomplete, make_review(h)]}, name="claude-opus-5-5")
    p = review_suggestions(m, sources, REQUIREMENTS, "# Dokument", h, 'review_1')
    assert len(p.decisions) == 3 and len(m.calls) == 2
    _, instructions, task = m.calls[0]
    assert "## Dokument" in task and "## Návrhy hodnotitele" in task and "V3" in task
    assert "harmonogram a hlavní milníky realizace" in instructions
    assert "V3" in m.calls[1][2] and "## Oprava" in m.calls[1][2]


def test_accepted_decisions_include_partial():
    p = SuggestionReview(decisions=[_decision("A", 'accepted'), _decision("B", 'rejected'),
                              _decision("C", 'partial')], summary="")
    assert [r.suggestion_id for r in accepted_decisions(p)] == ["A", "C"]


# ---------------------------------------------------------------- revision

def test_revision_missing_heading():
    h = make_evaluation(8)
    p = make_review(h)
    errors = validate_revision("# A\n# B\nx", "# A\nx", h, p)
    assert errors != [] and "# B" in errors[0]


def test_empty_revision():
    h = make_evaluation(8)
    assert validate_revision("# A\nx", "  \n", h, make_review(h)) != []


def test_shortened_revision_without_permission():
    h = make_evaluation(8)
    old = "# A\n" + "x" * 196
    new = "# A\n" + "x" * 96
    assert validate_revision(old, new, h, make_review(h)) != []


def test_shortened_revision_with_suggestion():
    h = make_evaluation(8, suggestions=1)
    h.suggestions[0].suggestion = "Zkrátit kap. 3 na polovinu."
    old = "# A\n" + "x" * 196
    new = "# A\n" + "x" * 96
    assert validate_revision(old, new, h, make_review(h)) == []


@pytest.mark.parametrize("text", [
    "Odstraňte duplicitní odstavec v kap. 2.",
    "zkrať úvod na tři věty",
    "ZKRAŤTE shrnutí.",
    "Vypusťte kapitolu 4.",
    "Smažte opakovaný popis týmu.",
    "Zrušte přílohu B.",
])
def test_shortened_revision_with_accented_suggestion(text):
    h = make_evaluation(8, suggestions=1)
    h.suggestions[0].suggestion = text
    old = "# A\n" + "x" * 196
    new = "# A\n" + "x" * 96
    assert validate_revision(old, new, h, make_review(h)) == []


def test_shortened_revision_with_accented_implementation():
    h = make_evaluation(8, suggestions=1)
    p = make_review(h)
    p.decisions[0].implementation = "Odstraň opakovaný odstavec."
    old = "# A\n" + "x" * 196
    new = "# A\n" + "x" * 96
    assert validate_revision(old, new, h, p) == []


def test_rejected_shortening_does_not_allow_short_revision():
    h = make_evaluation(8, suggestions=1)
    h.suggestions[0].suggestion = "Odstranit kap. 3."
    old = "# A\n" + "x" * 196
    new = "# A\n" + "x" * 96
    assert validate_revision(old, new, h, make_review(h, 'rejected')) != []


def test_revision_receives_only_accepted_suggestions(sources):
    h = make_evaluation(8, suggestions=0)
    h.suggestions = [_suggestion("H1", text="PRIJATY text"), _suggestion("H2", text="ODMITNUTY text"),
                _suggestion("H3", text="CASTECNY text")]
    p = SuggestionReview(decisions=[_decision("H1", 'accepted', implementation="Doplnit tabulku."),
                              _decision("H2", 'rejected', implementation="-"),
                              _decision("H3", 'partial', implementation="Jen první větu.")], summary="")
    old = "# Nabídka\n\n" + "Původní text. " * 10
    m = FakeModel({'draft': [old + " Doplněno."]}, name="claude-opus-5-5")
    new = incorporate_suggestions(m, sources, REQUIREMENTS, old, h, p, 'draft_2')
    assert new == old + " Doplněno."
    step, instructions, task = m.calls[0]
    assert step == 'draft_2'
    assert "## Dokument" in task and "## Přijaté návrhy k zapracování" in task
    assert "PRIJATY text" in task and "CASTECNY text" in task
    assert "Doplnit tabulku." in task and "Jen první větu." in task
    assert "ODMITNUTY text" not in task
    assert "harmonogram a hlavní milníky realizace" in instructions


def test_revision_repairs_missing_heading(sources):
    h = make_evaluation(8, suggestions=1)
    p = make_review(h)
    old = "# A\ntext\n# B\ntext"
    m = FakeModel({'draft': ["# A\ntext\ntext", old + "\nnové"]}, name="claude-opus-5-5")
    assert incorporate_suggestions(m, sources, REQUIREMENTS, old, h, p, 'draft_2') == old + "\nnové"
    assert len(m.calls) == 2 and "# B" in m.calls[1][2] and "## Oprava" in m.calls[1][2]


def test_revision_fails_after_second_invalid_response(sources):
    h = make_evaluation(8, suggestions=1)
    p = make_review(h)
    m = FakeModel({'draft': ["", ""]}, name="claude-opus-5-5")
    with pytest.raises(ModelError) as e:
        incorporate_suggestions(m, sources, REQUIREMENTS, "# A\ntext", h, p, 'draft_2')
    assert e.value.kind == 'invalid_output' and e.value.service == "Anthropic"
    assert e.value.raw_response == ""

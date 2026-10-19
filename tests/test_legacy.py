"""Compatibility with immutable Czech v1 runs and canonical English model schemas."""
import importlib
import json
from pathlib import Path
import shutil

import pytest

VARIABLES = {
    "request": "Poptávka testu.", "materials": "Podklady testu.", "document_type": "nabídka",
    "requirements": "N1", "structure_instructions": "Osnova", "criteria": "B1",
    "max_suggestions": "10", "rejected_suggestions": "(žádné)",
}
PROMPTS = ("requirements", "draft", "evaluation", "review", "revision", "comparison_criteria",
           "comparison_elements", "comparison_coverage")


def test_legacy_state_upgrade_preserves_paths_and_payloads(legacy_interrupted):
    from refiner.data import Evaluation
    from refiner.run import Run

    state_file = legacy_interrupted / "data/beh.json"
    original = state_file.read_bytes()
    step_file = legacy_interrupted / "data/04_hodnoceni_1.json"
    step_bytes = step_file.read_bytes()
    run = Run.open(legacy_interrupted)
    assert state_file.read_bytes() == original
    assert run.state.schema_version == 2 and run.state.status == "interrupted"
    assert run.state.profile_id == "proposal" and run.state.output_profile_name == "nabidka"
    assert run.is_done("evaluation_1") and run.is_done("draft_2")
    assert run.state.steps["draft_2"].file == "06_navrh_v2.md"
    assert run.data("evaluation_1", Evaluation).suggestions[0].priority == "medium"
    assert [usage.step for usage in run.state.usage] == [
        "requirements", "draft_1", "evaluation_1", "review_1", "draft_2"]
    run.save()
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["schema_version"] == 2 and saved["status"] == "interrupted"
    assert "kroky" not in saved and "steps" in saved
    assert not (run.directory / "data/run.json").exists()
    assert step_file.read_bytes() == step_bytes
    assert Run.open(run.directory).data("evaluation_1", Evaluation).criteria[0].score == 8.0


def test_legacy_resume_does_not_repeat_completed_calls(legacy_interrupted):
    from refiner.aplikace import obnov_beh
    from refiner.loop import run_loop
    from refiner.models.fakes import FakeModel
    from tests.helpers import make_evaluation

    run, sources = obnov_beh(legacy_interrupted)
    writer = FakeModel({})
    evaluator = FakeModel({"evaluation_2": [make_evaluation(9.5)]}, name="gpt-fake")
    result = run_loop(run, sources, writer, evaluator, lambda _: None)
    assert result.final_version == 2 and result.reason == "target_reached"
    assert writer.calls == []
    assert [step for step, *_ in evaluator.calls] == ["evaluation_2"]
    assert "criteria" in evaluator.calls[0][1] and "high" in evaluator.calls[0][1]
    assert (run.directory / "07_hodnoceni_2.md").is_file()


def test_missing_saved_score_reuses_evaluation(legacy_interrupted):
    from refiner.aplikace import obnov_beh
    from refiner.data import Evaluation
    from refiner.loop import run_loop
    from refiner.models.fakes import FakeModel
    from refiner.run import Run
    from tests.helpers import make_evaluation

    state_file = legacy_interrupted / "data/beh.json"
    payload = json.loads(state_file.read_text(encoding="utf-8"))
    del payload["skore"]["1"]
    state_file.write_text(json.dumps(payload), encoding="utf-8")
    old_step = (legacy_interrupted / "data/04_hodnoceni_1.json").read_bytes()
    run, sources = obnov_beh(legacy_interrupted)
    writer = FakeModel({})
    evaluator = FakeModel({"evaluation_2": [make_evaluation(9.5)]}, name="gpt-fake")
    run_loop(run, sources, writer, evaluator, lambda _: None)
    assert run.state.scores["1"].total == 8.3
    assert [step for step, *_ in evaluator.calls] == ["evaluation_2"] and writer.calls == []
    run.finish("interrupted", error="Další přerušení.")
    reopened = Run.open(run.directory)
    assert reopened.data("evaluation_1", Evaluation).criteria[0].score == 8.0
    assert reopened.data("evaluation_2", Evaluation).criteria[0].score == 9.5
    assert (legacy_interrupted / "data/04_hodnoceni_1.json").read_bytes() == old_step


@pytest.mark.parametrize("profile", ["custom_offer", "proposal"])
def test_custom_legacy_output_token_is_not_inferred_from_snapshot_filename(legacy_completed, profile):
    from refiner.aplikace import otevri_dokonceny

    state_file = legacy_completed / "data/beh.json"
    payload = json.loads(state_file.read_text(encoding="utf-8"))
    payload["profil"] = profile
    state_file.write_text(json.dumps(payload), encoding="utf-8")
    run, sources = otevri_dokonceny(legacy_completed)
    assert run.state.output_profile_name == profile
    assert sources.configuration.output_profile_name == profile


@pytest.mark.parametrize("invalid", ["{broken", "[]", '{"schema_version": 99}', '{"schema_version": true}'])
def test_malformed_or_future_state_is_a_czech_input_error_without_overwrite(legacy_interrupted, invalid):
    from refiner.aplikace import obnov_beh
    from refiner.input import InputError

    state_file = legacy_interrupted / "data/beh.json"
    state_file.write_text(invalid, encoding="utf-8")
    before = state_file.read_bytes()
    with pytest.raises(InputError, match="Stav běhu.*nelze přečíst"):
        obnov_beh(legacy_interrupted)
    assert state_file.read_bytes() == before


def test_typed_state_normalization_does_not_translate_user_content(legacy_interrupted):
    from refiner.legacy import normalize_run_state

    payload = json.loads((legacy_interrupted / "data/beh.json").read_text(encoding="utf-8"))
    payload["vstup"] = "hodnoceni_1_poptavka.md"
    payload["varovani"] = ["navrh_1 a rozhodnuti jsou slova uživatele."]
    payload["spotreba"][0]["model"] = "hodnoceni_1"
    normalized = normalize_run_state(payload)
    assert normalized["input"] == "hodnoceni_1_poptavka.md"
    assert normalized["warnings"] == payload["varovani"]
    assert normalized["usage"][0]["model"] == "hodnoceni_1"
    assert normalized["steps"]["draft_2"]["file"] == "06_navrh_v2.md"
    assert "schema_version" not in payload


def test_legacy_prompt_uses_canonical_schema_tokens(legacy_interrupted):
    from refiner.steps import render_prompt

    directory = legacy_interrupted / "data/konfigurace/prompty"
    before = (directory / "hodnoceni.md").read_bytes()
    rendered = render_prompt(directory, "evaluation", **VARIABLES)
    assert "${" not in rendered
    assert "criteria" in rendered and "priority" in rendered and "high" in rendered
    assert "1–10" in rendered and "0,5" in rendered and "[DOPLNIT: …]" in rendered
    assert "Celkové skóre **nepočítej**" in rendered
    assert (directory / "hodnoceni.md").read_bytes() == before


def test_legacy_review_disambiguates_decisions_and_decision(legacy_interrupted):
    from refiner.steps import render_prompt

    rendered = render_prompt(legacy_interrupted / "data/konfigurace/prompty", "review", **VARIABLES)
    assert "rozhodnuti → decisions" in rendered
    assert "rozhodnuti[].rozhodnuti → decisions[].decision" in rendered
    assert "Každý návrh posuď **sokratovsky**" in rendered


@pytest.mark.parametrize("name", PROMPTS)
@pytest.mark.parametrize("saved", [False, True])
def test_new_source_and_snapshot_prompts_render_without_legacy_note(tmp_path, repo_root, name, saved):
    from refiner.artifacts import PROMPT_SNAPSHOT_NAMES
    from refiner.legacy import adapt_legacy_prompt
    from refiner.steps import render_prompt

    source = repo_root / "prompts" / f"{name}.md"
    directory = tmp_path / "prompts"
    directory.mkdir()
    target = directory / (PROMPT_SNAPSHOT_NAMES[name] if saved else source.name)
    shutil.copyfile(source, target)
    raw = source.read_text(encoding="utf-8")
    assert adapt_legacy_prompt(raw, name) == raw
    rendered = render_prompt(directory, name, **VARIABLES)
    assert "${" not in rendered and "Technické názvy polí" not in rendered
    assert "Poptávka testu." in rendered


@pytest.mark.parametrize("name", PROMPTS)
def test_all_frozen_prompt_snapshots_render(legacy_interrupted, name):
    from refiner.steps import render_prompt

    assert "${" not in render_prompt(legacy_interrupted / "data/konfigurace/prompty", name, **VARIABLES)


def test_canonical_prompt_name_has_precedence_and_unknown_variables_fail(tmp_path):
    from refiner.configuration import ConfigurationError
    from refiner.steps import render_prompt

    (tmp_path / "evaluation.md").write_text("${request} ENGLISH", encoding="utf-8")
    (tmp_path / "hodnoceni.md").write_text("LEGACY", encoding="utf-8")
    assert render_prompt(tmp_path, "evaluation", request="TEST") == "TEST ENGLISH"
    (tmp_path / "evaluation.md").write_text("${unknown}", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="neznámá proměnná"):
        render_prompt(tmp_path, "evaluation", request="TEST")


@pytest.mark.parametrize("step,expected", [
    ("poptavka", "request"), ("nalezitosti", "requirements"), ("navrh_2", "draft_2"),
    ("hodnoceni_1", "evaluation_1"), ("posouzeni_3", "review_3"),
    ("porovnani_kalibrace", "comparison_calibration"), ("porovnani_srovnani_1", "comparison_pair_1"),
    ("porovnani_srovnani_2", "comparison_pair_2"), ("porovnani_prvky", "comparison_elements"),
    ("porovnani_pokryti", "comparison_coverage"), ("unrelated_poptavka", "unrelated_poptavka"),
])
def test_explicit_step_identifier_normalization(step, expected):
    from refiner.legacy import normalize_step_id

    assert normalize_step_id(step) == expected


@pytest.mark.parametrize("class_name,relative,keys", [
    ("RequirementsOutput", "data/02_nalezitosti.json", {"requirements"}),
    ("Evaluation", "data/04_hodnoceni_1.json", {"criteria", "fabricated_facts", "claims_to_verify", "suggestions", "overall_comment"}),
    ("SuggestionReview", "data/05_posouzeni_1.json", {"decisions", "summary"}),
])
def test_frozen_model_payloads_dump_and_expose_english_schema(legacy_interrupted, class_name, relative, keys):
    model = getattr(importlib.import_module("refiner.data"), class_name)
    decoded = model.model_validate_json((legacy_interrupted / relative).read_text(encoding="utf-8"))
    assert set(decoded.model_dump()) == keys
    assert set(model.model_json_schema()["properties"]) == keys


@pytest.mark.parametrize("module,class_name,payload,expected", [
    ("refiner.data", "Requirement", {"id": "N1", "text": "citace", "citace": "hodnoceni_1"}, {"id": "N1", "text": "citace", "citation": "hodnoceni_1"}),
    ("refiner.data", "Criterion", {"id": "N1", "nazev": "název", "popis": "popis", "vaha": 1, "skupina": "A"}, {"id": "N1", "name": "název", "description": "popis", "weight": 1, "group": "A"}),
    ("refiner.data", "TokenUsage", {"krok": "hodnoceni_1", "model": "hodnoceni_1", "vstup": 1, "vystup": 2}, {"step": "evaluation_1", "model": "hodnoceni_1", "input_tokens": 1, "output_tokens": 2, "cache_read_tokens": 0, "cache_write_tokens": 0, "subscription": False}),
    ("refiner.comparison", "PairComparison", {"kriteria": [{"id": "B1", "lepsi": "stejne", "zduvodneni": "Stejné."}]}, {"criteria": [{"id": "B1", "better": "tie", "rationale": "Stejné."}]}),
    ("refiner.comparison", "ReferenceElements", {"prvky": [{"id": "P1", "popis": "Prvek."}]}, {"elements": [{"id": "P1", "description": "Prvek."}]}),
    ("refiner.comparison", "Coverage", {"polozky": [{"id": "P1", "stav": "chybi", "komentar": "Chybí."}]}, {"items": [{"id": "P1", "status": "missing", "comment": "Chybí."}]}),
])
def test_legacy_typed_aliases_preserve_text_and_canonical_serialization(module, class_name, payload, expected):
    model = getattr(importlib.import_module(module), class_name)
    assert model.model_validate(payload).model_dump() == expected
    assert set(model.model_json_schema()["properties"]) == set(expected)


@pytest.mark.parametrize("module,class_name", [
    *(('refiner.data', name) for name in ("Requirement", "RequirementsOutput", "CriterionScore", "FabricatedFact", "ClaimToVerify", "RevisionSuggestion", "Evaluation", "SuggestionDecision", "SuggestionReview")),
    *(('refiner.comparison', name) for name in ("CriterionComparison", "PairComparison", "ReferenceElement", "ReferenceElements", "ElementCoverage", "Coverage")),
])
def test_model_schemas_keep_every_field_required_and_without_defaults_or_ranges(module, class_name):
    model = getattr(importlib.import_module(module), class_name)
    schema = model.model_json_schema()
    for definition in [schema, *schema.get("$defs", {}).values()]:
        if "properties" in definition:
            assert set(definition["required"]) == set(definition["properties"])
            for field in definition["properties"].values():
                assert not {"default", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"} & field.keys()


def test_legacy_comparison_result_normalizes_verdict_values_without_translating_ids():
    from refiner.comparison import ComparisonResult

    score = {"a": 9, "b": 9, "c": 10, "celkem": 9.2, "cil_splnen": False, "duvody_nesplneni": []}
    result = ComparisonResult.model_validate({
        "skore_reference": score, "skore_generovane": score,
        "srovnani": {"generovana": "generovana", "reference": "reference", "nerozhodne": "nerozhodne"},
        "zduvodneni": {"generovana": ["generovana je citace uživatele."]}, "prvky": [], "pokryti": [],
    })
    assert result.comparison == {"generovana": "generated", "reference": "reference", "nerozhodne": "tie"}
    assert result.rationales == {"generovana": ["generovana je citace uživatele."]}
    assert set(result.model_dump()) == {
        "reference_score", "generated_score", "comparison", "rationales", "elements", "coverage"}


def test_canonical_aliases_win_and_state_containers_are_independent(legacy_interrupted):
    from refiner.data import Requirement
    from refiner.run import RunState

    assert Requirement.model_validate({"id": "N1", "text": "text", "citation": "English key",
                                       "citace": "Czech key"}).citation == "English key"
    old = json.loads((legacy_interrupted / "data/beh.json").read_text(encoding="utf-8"))
    old["input"] = "canonical.md"
    assert RunState.model_validate(old).input == "canonical.md"
    first = RunState(input="a", profile_id="proposal", output_profile_name="nabidka", created_at=old["vytvoreno"])
    second = RunState(input="b", profile_id="proposal", output_profile_name="nabidka", created_at=old["vytvoreno"])
    first.warnings.append("varování")
    first.steps["request"] = {"number": 1, "file": "01_poptavka.md"}
    assert second.warnings == [] and second.steps == {} and second.usage == [] and second.scores == {}

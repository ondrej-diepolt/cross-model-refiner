"""Reference comparison regressions (design section 11)."""
import io
import os
import shutil
from pathlib import Path

import pytest

from refiner.run import Run
from refiner.cli import main
from refiner.data import Evaluation
from refiner.models.errors import ModelError
from refiner.models.fakes import FakeModel, demo_models
from refiner.comparison import (
    FORM_QUESTIONS,
    Coverage,
    ElementCoverage,
    ReferenceElement,
    ReferenceElements,
    PairComparison,
    CriterionComparison,
    ComparisonResult,
    find_reference,
    compare,
    combine_comparisons,
)
from refiner.loop import run_loop
from refiner.input import InputError
from tests.helpers import TEST_REQUEST, make_run, make_evaluation, make_criteria, scripted_models


def test_legacy_comparison_preserves_filled_form_and_czech_labels(legacy_completed):
    import re
    from refiner.aplikace import otevri_dokonceny

    run, sources = otevri_dokonceny(legacy_completed)
    form = legacy_completed / "porovnani_formular.md"
    before = form.read_bytes()
    state_before = run.state.model_dump(exclude={"usage"})
    evaluator = _evaluator()
    path = compare(run, sources, REFERENCE, evaluator, lambda _: None)
    html = path.read_text(encoding="utf-8")
    assert path.name == "porovnani.html" and (run.directory / "data/porovnani.json").is_file()
    assert form.read_bytes() == before and "Odpověď: ano, 30 minut" in form.read_text(encoding="utf-8")
    assert run.state.model_dump(exclude={"usage"}) == state_before
    assert len(evaluator.calls) == 5
    assert 'href="FINALNI_nabidka.md"' in html
    assert "lepší generovaná" in html and "částečně" in html and "chybí" in html
    visible = re.sub(r"<style>.*?</style>", "", html, flags=re.S)
    visible = re.sub(r"<[^>]+>", "", visible).replace(run.directory.name, "")
    assert not re.search(r"\b(generated|present|partial|missing|completed|accepted|rejected)\b", visible)
    assert not (run.directory / "comparison.html").exists()


def test_comparison_refresh_preserves_saved_evaluation(legacy_completed, repo_root):
    from refiner.aplikace import obnov_prompty_porovnani, otevri_dokonceny

    run, sources = otevri_dokonceny(legacy_completed)
    snapshot = run.directory / "data/konfigurace/prompty"
    saved = {p.name: p.read_bytes() for p in snapshot.glob("*.md")}
    form_before = (run.directory / "porovnani_formular.md").read_bytes()
    old_usage = len(run.state.usage)
    obnov_prompty_porovnani(run, repo_root / "prompts")
    for source, destination in (
        ("comparison_criteria.md", "porovnani_kriteria.md"),
        ("comparison_elements.md", "porovnani_prvky.md"),
        ("comparison_coverage.md", "porovnani_pokryti.md"),
    ):
        assert (snapshot / destination).read_bytes() == (repo_root / "prompts" / source).read_bytes()
    for name in ("hodnoceni.md", "navrh.md", "posouzeni.md", "nalezitosti.md", "zapracovani.md"):
        assert (snapshot / name).read_bytes() == saved[name]
    for _ in range(2):
        evaluator = _evaluator()
        assert compare(run, sources, REFERENCE, evaluator, lambda _: None).name == "porovnani.html"
        assert len(evaluator.calls) == 5 and all("${" not in instructions for _, instructions, _ in evaluator.calls)
        assert "Technické názvy polí" in evaluator.calls[0][1]
        assert all("Technické názvy polí" not in instructions for _, instructions, _ in evaluator.calls[1:])
    assert (snapshot / "hodnoceni.md").read_bytes() == saved["hodnoceni.md"]
    assert (run.directory / "porovnani_formular.md").read_bytes() == form_before
    assert len(run.state.usage) == old_usage + 10 and run.state.status == "completed"


@pytest.mark.parametrize("profile_id,token", [("policy", "smernice"), ("custom_offer", "custom_offer")])
def test_comparison_links_preserve_output_profile_tokens(legacy_completed, profile_id, token):
    from dataclasses import replace
    from refiner.aplikace import otevri_dokonceny

    run, sources = otevri_dokonceny(legacy_completed)
    configuration = replace(sources.configuration, profile_id=profile_id, output_profile_name=token)
    sources = replace(sources, configuration=configuration)
    run.write_fixed(f"FINALNI_{token}.md", "# Dokument\n")
    html = compare(run, sources, REFERENCE, _evaluator(), lambda _: None).read_text(encoding="utf-8")
    assert f'href="FINALNI_{token}.md"' in html
    assert "FINAL_policy" not in html and "FINAL_custom_offer" not in html

MARKER = "REFERENCNI-ZNACKA"
REFERENCE = f"# Nabídka dodavatele\n\nRučně dotažená nabídka {MARKER}.\n"
STEPS = ['comparison_calibration', 'comparison_pair_1', 'comparison_pair_2',
         'comparison_elements', 'comparison_coverage']


def k(id_: str, better: str, rationale: str = "Zdůvodnění.") -> CriterionComparison:
    return CriterionComparison(id=id_, better=better, rationale=rationale)


def _elements(*descriptions: str) -> ReferenceElements:
    return ReferenceElements(elements=[ReferenceElement(id=f"P{i}", description=p) for i, p in enumerate(descriptions, start=1)])


def _coverage(*statuses: tuple[str, str]) -> Coverage:
    return Coverage(items=[ElementCoverage(id=f"P{i}", status=s, comment=c)
                            for i, (s, c) in enumerate(statuses, start=1)])


def _evaluator(**overrides) -> FakeModel:
    """Fake evaluator for five comparison steps; criteria include N1-N3 and the profile."""
    ids = [x.id for x in make_criteria(3)]
    responses = {
        'comparison_calibration': [make_evaluation(9.0, suggestions=0)],
        'comparison_pair_1': [PairComparison(criteria=[k(i, "A") for i in ids])],
        'comparison_pair_2': [PairComparison(criteria=[k(i, "B") for i in ids])],
        'comparison_elements': [_elements("Závazný cenový strop", "Kritéria převzetí po etapách", "Definice vady")],
        'comparison_coverage': [_coverage(('present', "Kap. 2."), ('missing', "Nikde."), ('partial', "Jen obecně."))],
    }
    responses.update(overrides)
    return FakeModel(responses, name="gpt-falesny")


def _completed_run(tmp_path: Path, sources) -> tuple[Run, FakeModel]:
    run = make_run(tmp_path, sources)
    writer, evaluator = scripted_models([9.5])
    result = run_loop(run, sources, writer, evaluator, lambda _: None)
    run.finish('completed', result.reason, final_version=result.final_version)
    return run, writer


def _silent(_: str) -> None:
    pass


# ---------------------------------------------------------------- pure functions

def test_combine_comparisons():
    s1 = PairComparison(criteria=[k("B1", "A"), k("B2", "B"), k("B3", "A"), k("B4", 'tie')])
    s2 = PairComparison(criteria=[k("B1", "B"), k("B2", "A"), k("B3", "A"), k("B4", 'tie')])
    assert combine_comparisons(s1, s2) == {
        "B1": 'generated', "B2": "reference", "B3": 'tie', "B4": 'tie'}


def test_tie_in_one_order_gives_tied_verdict():
    s1 = PairComparison(criteria=[k("B1", "A")])
    s2 = PairComparison(criteria=[k("B1", 'tie')])
    assert combine_comparisons(s1, s2) == {"B1": 'tie'}


@pytest.mark.parametrize("files", [["reference.docx"], ["Nabídka NRB.md"]])
def test_find_reference_single_file(tmp_path, files):
    (tmp_path / "examples").mkdir()
    for n in files:
        (tmp_path / "examples" / n).write_text("x", encoding="utf-8")
    (tmp_path / "examples" / "~$docasny.docx").write_text("x", encoding="utf-8")
    assert find_reference(tmp_path) == tmp_path / "examples" / files[0]


@pytest.mark.parametrize("files", [[], ["a.md", "b.docx"], None])
def test_find_reference_other_counts_fail(tmp_path, files):
    if files is not None:
        (tmp_path / "examples").mkdir()
        for n in files:
            (tmp_path / "examples" / n).write_text("x", encoding="utf-8")
    with pytest.raises(InputError) as e:
        find_reference(tmp_path)
    assert "--reference" in str(e.value)


# ---------------------------------------------------------------- compare

def test_compare_writes_outputs(tmp_path, sources):
    run, _ = _completed_run(tmp_path, sources)
    evaluator = _evaluator()
    html = compare(run, sources, REFERENCE, evaluator, print).read_text(encoding="utf-8")
    assert "Kalibrace" in html and (run.directory / "porovnani_formular.md").exists()
    assert [step for step, *_ in evaluator.calls] == STEPS
    assert 'href="porovnani_formular.md"' in html

    v = ComparisonResult.model_validate_json(
        (run.directory / "data" / "porovnani.json").read_text(encoding="utf-8"))
    assert v.generated_score == run.state.scores["1"]
    assert v.reference_score.total == 9.2   # 0,5·9 + 0,35·9 + 0,15·10
    assert set(v.comparison.values()) == {'generated'}
    assert list(v.comparison) == [x.id for x in make_criteria(3)]
    assert len(v.rationales["B1"]) == 2
    assert [p.id for p in v.elements] == ["P1", "P2", "P3"]
    assert [p.status for p in v.coverage] == ['present', 'missing', 'partial']


def test_form_contains_design_questions(tmp_path, sources):
    run, _ = _completed_run(tmp_path, sources)
    compare(run, sources, REFERENCE, _evaluator(), _silent)
    form = (run.directory / "porovnani_formular.md").read_text(encoding="utf-8")
    assert FORM_QUESTIONS == (
        "Odeslal bych to po doplnění placeholderů?",
        "Kolik minut práce do odeslatelné verze?",
        "Věcné chyby?",
        "Co chybí?",
        "Co je lepší než v referenci?",
    )
    for question in FORM_QUESTIONS:
        assert question in form
    assert form.count("Odpověď:") == len(FORM_QUESTIONS)


def test_comparison_reverses_document_order(tmp_path, sources):
    run, _ = _completed_run(tmp_path, sources)
    generated = run.text('draft_1')
    evaluator = _evaluator()
    compare(run, sources, REFERENCE, evaluator, _silent)
    task = {step: z for step, _, z in evaluator.calls}
    z1, z2 = task['comparison_pair_1'], task['comparison_pair_2']
    assert z1.index(generated) < z1.index(MARKER)
    assert z2.index(MARKER) < z2.index(generated)
    instructions = {step: i for step, i, _ in evaluator.calls}
    # A/B labels conceal which document is generated and which is the reference.
    for text in (z1.replace(MARKER, ""), z2.replace(MARKER, "")):
        assert "referen" not in text.lower() and "generovan" not in text.lower()
    assert "referenční" not in instructions['comparison_pair_1'].lower()
    assert "generovan" not in instructions['comparison_pair_1'].lower()
    assert instructions['comparison_pair_1'] == instructions['comparison_pair_2']


def test_calibration_evaluates_reference_with_same_criteria(tmp_path, sources):
    run, _ = _completed_run(tmp_path, sources)
    evaluator = _evaluator()
    compare(run, sources, REFERENCE, evaluator, _silent)
    step, instructions, task = evaluator.calls[0]
    assert MARKER in task and "**N1**" in instructions and "**B1**" in instructions
    assert TEST_REQUEST.strip() in instructions
    # Extract elements from the reference, then check coverage in the generated document.
    step_tasks = {step: z for step, _, z in evaluator.calls}
    assert MARKER in step_tasks['comparison_elements']
    assert MARKER not in step_tasks['comparison_coverage']
    assert run.text('draft_1') in step_tasks['comparison_coverage']
    assert "**P2** Kritéria převzetí po etapách" in step_tasks['comparison_coverage']


def test_writer_never_sees_reference(tmp_path, sources):
    run, writer = _completed_run(tmp_path, sources)
    evaluator = _evaluator()
    compare(run, sources, REFERENCE, evaluator, _silent)
    assert writer.calls, "writer should have worked during generation"
    for _, instructions, task in writer.calls:
        assert MARKER not in instructions and MARKER not in task
    assert any(MARKER in z for _, _, z in evaluator.calls)


def test_compare_rejects_incomplete_run(tmp_path, sources):
    run = make_run(tmp_path, sources)
    evaluator = _evaluator()
    with pytest.raises(InputError):
        compare(run, sources, REFERENCE, evaluator, _silent)
    assert evaluator.calls == []


def test_compare_preserves_run_state_and_adds_usage(tmp_path, sources):
    run, _ = _completed_run(tmp_path, sources)
    before = Run.open(run.directory).state
    compare(run, sources, REFERENCE, _evaluator(), _silent)
    after = Run.open(run.directory).state
    assert after.status == 'completed' and after.ended_at == before.ended_at
    assert after.steps == before.steps and after.scores == before.scores
    assert after.final_version == before.final_version and after.stop_reason == before.stop_reason
    assert [s.step for s in after.usage[len(before.usage):]] == STEPS


def test_repeated_comparison_replaces_reports(tmp_path, sources):
    run, _ = _completed_run(tmp_path, sources)
    compare(run, sources, REFERENCE, _evaluator(), _silent)
    files = sorted(p.name for p in run.directory.iterdir())
    form = run.directory / "porovnani_formular.md"
    form.write_text(form.read_text(encoding="utf-8").replace(
        "Odpověď:", "Odpověď: ano, 30 minut", 1), encoding="utf-8")

    evaluator = _evaluator(comparison_coverage=[_coverage(('present', "A"), ('present', "B"), ('present', "C"))])
    compare(run, sources, REFERENCE, evaluator, _silent)

    assert sorted(p.name for p in run.directory.iterdir()) == files
    assert "Odpověď: ano, 30 minut" in form.read_text(encoding="utf-8")
    v = ComparisonResult.model_validate_json(
        (run.directory / "data" / "porovnani.json").read_text(encoding="utf-8"))
    assert [p.status for p in v.coverage] == ['present', 'present', 'present']
    assert len([s for s in Run.open(run.directory).state.usage if s.step.startswith("comparison_")]) == 10


def test_html_escapes_model_output(tmp_path, sources):
    run, _ = _completed_run(tmp_path, sources)
    ids = [x.id for x in make_criteria(3)]
    calibration = make_evaluation(9.0, suggestions=0)
    calibration.criteria[0].rationale = "<script>alert(0)</script>"
    evaluator = _evaluator(
        comparison_calibration=[calibration],
        comparison_pair_1=[PairComparison(criteria=[k(i, "A", "<script>alert(1)</script>") for i in ids])],
        comparison_elements=[_elements("<script>alert(2)</script>", "<b>tučně</b>", "Definice vady")],
        comparison_coverage=[_coverage(('present', "<script>alert(3)</script>"), ('missing', "x"), ('present', "y"))],
    )
    html = compare(run, sources, REFERENCE, evaluator, _silent).read_text(encoding="utf-8")
    assert "<script" not in html and "<b>tučně</b>" not in html
    for n in range(4):
        assert f"&lt;script&gt;alert({n})" in html


def test_coverage_lists_missing_elements_first(tmp_path, sources):
    run, _ = _completed_run(tmp_path, sources)
    evaluator = _evaluator(
        comparison_elements=[_elements("PRVEK-JE", "PRVEK-CASTECNE", "PRVEK-CHYBI")],
        comparison_coverage=[_coverage(('present', "k1"), ('partial', "k2"), ('missing', "k3"))],
    )
    html = compare(run, sources, REFERENCE, evaluator, _silent).read_text(encoding="utf-8")
    assert html.index("PRVEK-CHYBI") < html.index("PRVEK-CASTECNE") < html.index("PRVEK-JE")


@pytest.mark.parametrize("score, expected", [(9.5, "Reference dosáhla cílového skóre"),
                                              (7.5, "Reference nedosáhla cílového skóre")])
def test_calibration_target_sentence(tmp_path, sources, score, expected):
    run, _ = _completed_run(tmp_path, sources)
    evaluator = _evaluator(comparison_calibration=[make_evaluation(score, suggestions=0)])
    html = compare(run, sources, REFERENCE, evaluator, _silent).read_text(encoding="utf-8")
    assert expected in html


# ---------------------------------------------------------------- validation and repair

def test_comparison_repairs_missing_criterion(tmp_path, sources):
    run, _ = _completed_run(tmp_path, sources)
    ids = [x.id for x in make_criteria(3)]
    incomplete = PairComparison(criteria=[k(i, "A") for i in ids[1:]] + [k("X9", "A")])
    complete = PairComparison(criteria=[k(i, "A") for i in ids])
    evaluator = _evaluator(comparison_pair_1=[incomplete, complete])
    compare(run, sources, REFERENCE, evaluator, _silent)
    calls = [(step, z) for step, _, z in evaluator.calls if step == 'comparison_pair_1']
    assert len(calls) == 2
    assert "## Oprava" in calls[1][1] and "N1" in calls[1][1] and "X9" in calls[1][1]


def test_duplicate_after_repair_keeps_usage_and_raises(tmp_path, sources):
    run, _ = _completed_run(tmp_path, sources)
    ids = [x.id for x in make_criteria(3)]
    duplicate = PairComparison(criteria=[k(i, "A") for i in ids] + [k("N1", "B")])
    evaluator = _evaluator(comparison_pair_2=[duplicate, duplicate])
    with pytest.raises(ModelError) as e:
        compare(run, sources, REFERENCE, evaluator, _silent)
    assert e.value.kind == 'invalid_output' and "N1" in e.value.detail
    usage = [s.step for s in Run.open(run.directory).state.usage if s.step.startswith("comparison_")]
    assert usage == STEPS[:2] + ['comparison_pair_2'] * 2
    assert not (run.directory / "porovnani.html").exists()


def test_coverage_requires_every_element(tmp_path, sources):
    run, _ = _completed_run(tmp_path, sources)
    incomplete = Coverage(items=[ElementCoverage(id="P1", status='present', comment="x")])
    evaluator = _evaluator(comparison_coverage=[incomplete, _coverage(('present', "a"), ('present', "b"), ('present', "c"))])
    compare(run, sources, REFERENCE, evaluator, _silent)
    repair = [z for step, _, z in evaluator.calls if step == 'comparison_coverage'][1]
    assert "## Oprava" in repair and "P2" in repair and "P3" in repair


@pytest.mark.parametrize('elements', [ReferenceElements(elements=[]),
                                   ReferenceElements(elements=[ReferenceElement(id="P1", description="a"),
                                                      ReferenceElement(id="P1", description="b")])])
def test_empty_or_duplicate_elements_are_repaired(tmp_path, sources, elements):
    run, _ = _completed_run(tmp_path, sources)
    evaluator = _evaluator(comparison_elements=[elements, _elements("a", "b", "c")])
    compare(run, sources, REFERENCE, evaluator, _silent)
    assert [step for step, *_ in evaluator.calls].count('comparison_elements') == 2


# ---------------------------------------------------------------- command line

@pytest.fixture
def app_root(tmp_path, repo_root) -> Path:
    """Temporary app root with configuration, prompts, request, and reference."""
    root = tmp_path / "app"
    root.mkdir()
    shutil.copy(repo_root / "settings.yaml", root / "settings.yaml")
    shutil.copytree(repo_root / "profiles", root / "profiles")
    shutil.copytree(repo_root / 'prompts', root / 'prompts')
    (root / "input").mkdir()
    (root / "input" / "poptavka.md").write_text(TEST_REQUEST, encoding="utf-8")
    (root / "examples").mkdir()
    (root / "examples" / "reference.md").write_text(REFERENCE, encoding="utf-8")
    return root


def _completed_run_cli(app_root: Path, dry_run: bool = False) -> tuple[Path, FakeModel]:
    """Complete a fake live run, setting test credentials only during generation.

    Subsequent comparison tests independently control which keys are available."""
    models = demo_models()
    argv = ["--nanecisto"] if dry_run else []
    before = set((app_root / "output").iterdir()) if (app_root / "output").exists() else set()
    if not dry_run:
        os.environ["ANTHROPIC_API_KEY"] = os.environ["OPENAI_API_KEY"] = "test-klic"
    try:
        assert main(argv, koren=app_root, vstup_fn=lambda _: "1", vystup=io.StringIO(),
                    tovarna_modelu=lambda configuration, n: models) == 0
    finally:
        if not dry_run:
            os.environ.pop("ANTHROPIC_API_KEY", None)
            os.environ.pop("OPENAI_API_KEY", None)
    (directory,) = set((app_root / "output").iterdir()) - before
    return directory, models[0]


def test_cli_compare_rejects_demo_run(app_root, monkeypatch):
    directory, _ = _completed_run_cli(app_root, dry_run=True)
    assert Run.open(directory).state.dry_run
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    evaluator = _evaluator()
    out = io.StringIO()
    assert main(["porovnat", directory.name], koren=app_root, vystup=out,
                tovarna_modelu=lambda configuration, n: (FakeModel({}), evaluator)) == 2
    assert "ukázkový" in out.getvalue() and evaluator.calls == []
    assert not (directory / "porovnani.html").exists()


def test_cli_compare_latest_skips_demo_runs(app_root, monkeypatch):
    live, _ = _completed_run_cli(app_root)
    demo, _ = _completed_run_cli(app_root, dry_run=True)   # newer
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    assert main(["porovnat"], koren=app_root, vystup=io.StringIO(),
                tovarna_modelu=lambda configuration, n: (FakeModel({}), _evaluator())) == 0
    assert (live / "porovnani.html").exists() and not (demo / "porovnani.html").exists()


def test_cli_compare_only_demo_runs_returns_2(app_root, monkeypatch):
    _completed_run_cli(app_root, dry_run=True)
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    out = io.StringIO()
    assert main(["porovnat"], koren=app_root, vystup=out,
                tovarna_modelu=lambda configuration, n: (FakeModel({}), _evaluator())) == 2
    assert "ukázkové" in out.getvalue()


def test_cli_compare_without_directory(app_root, monkeypatch):
    directory, run_writer = _completed_run_cli(app_root)
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    writer, evaluator = FakeModel({}, name="claude-falesny"), _evaluator()
    out = io.StringIO()
    assert main(["porovnat"], koren=app_root, vystup=out,
                tovarna_modelu=lambda configuration, dry_run: (writer, evaluator)) == 0
    assert (directory / "porovnani.html").exists()
    assert [step for step, *_ in evaluator.calls] == STEPS
    assert any(MARKER in z for _, _, z in evaluator.calls)
    # Generation never reads examples/, so the writer never saw the reference.
    assert writer.calls == []
    for _, instructions, task in run_writer.calls:
        assert MARKER not in instructions and MARKER not in task
    assert "porovnani.html" in out.getvalue()


def test_cli_compare_requires_only_openai_key(app_root, monkeypatch):
    _completed_run_cli(app_root)
    settings = app_root / "settings.yaml"   # Credentials are checked only in API mode.
    settings.write_text(settings.read_text(encoding="utf-8").replace("mode: subscription", "mode: api"),
                         encoding="utf-8")
    out = io.StringIO()
    assert main(["porovnat"], koren=app_root, vystup=out) == 2
    assert "OPENAI_API_KEY" in out.getvalue() and "ANTHROPIC_API_KEY" not in out.getvalue()


def test_cli_compare_directory_and_reference(app_root, monkeypatch, tmp_path):
    directory, _ = _completed_run_cli(app_root)
    (app_root / "examples" / "druha.md").write_text("# Druhá", encoding="utf-8")   # ambiguous examples/
    alternate = tmp_path / "jina_reference.md"
    alternate.write_text("# Jiná reference JINA-ZNACKA", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    evaluator = _evaluator()
    assert main(["porovnat", directory.name, "--reference", str(alternate)], koren=app_root, vystup=io.StringIO(),
                tovarna_modelu=lambda configuration, dry_run: (FakeModel({}), evaluator)) == 0
    assert "JINA-ZNACKA" in evaluator.calls[0][2]


def test_cli_compare_ambiguous_reference(app_root, monkeypatch):
    _completed_run_cli(app_root)
    (app_root / "examples" / "druha.md").write_text("# Druhá", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    out = io.StringIO()
    assert main(["porovnat"], koren=app_root, vystup=out,
                tovarna_modelu=lambda configuration, dry_run: (FakeModel({}), _evaluator())) == 2
    assert "--reference" in out.getvalue()


def test_cli_compare_missing_reference(app_root, monkeypatch):
    _completed_run_cli(app_root)
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    out = io.StringIO()
    assert main(["porovnat", "--reference", "neni.docx"], koren=app_root, vystup=out,
                tovarna_modelu=lambda configuration, dry_run: (FakeModel({}), _evaluator())) == 2
    assert "neni.docx" in out.getvalue()


def test_cli_compare_no_completed_run(app_root, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    out = io.StringIO()
    assert main(["porovnat"], koren=app_root, vystup=out,
                tovarna_modelu=lambda configuration, dry_run: (FakeModel({}), _evaluator())) == 2
    assert "dokončený" in out.getvalue()


def test_cli_compare_explicit_incomplete_run(app_root, monkeypatch):
    assert main(["--nanecisto"], koren=app_root, vstup_fn=lambda _: "1", vystup=io.StringIO(),
                tovarna_modelu=lambda configuration, dry_run: (
                    demo_models()[0], FakeModel({'evaluation_1': [ModelError('network', "OpenAI")]}))) == 1
    directory = next((app_root / "output").iterdir())
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    out = io.StringIO()
    assert main(["porovnat", str(directory)], koren=app_root, vystup=out,
                tovarna_modelu=lambda configuration, dry_run: (FakeModel({}), _evaluator())) == 2
    assert "dokončen" in out.getvalue()


def test_cli_compare_model_error_returns_1(app_root, monkeypatch):
    directory, _ = _completed_run_cli(app_root)
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    evaluator = _evaluator(comparison_elements=[ModelError('overloaded', "OpenAI")])
    out = io.StringIO()
    assert main(["porovnat"], koren=app_root, vystup=out,
                tovarna_modelu=lambda configuration, dry_run: (FakeModel({}), evaluator)) == 1
    assert "porovnat.bat" in out.getvalue() and "pokracovat.bat" not in out.getvalue()
    state = Run.open(directory).state
    assert state.status == 'completed'
    assert [s.step for s in state.usage if s.step.startswith("comparison_")] == STEPS[:3]
    assert "Chyba modelu při porovnání" in (directory / "data" / "beh.log").read_text(encoding="utf-8")


def test_cli_compare_saves_raw_response(app_root, monkeypatch):
    directory, _ = _completed_run_cli(app_root)
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    error = ModelError('invalid_output', "OpenAI", detail="x", raw_response="SUROVA-ODPOVED")
    evaluator = _evaluator(comparison_calibration=[error, error])   # still invalid after repair
    assert main(["porovnat"], koren=app_root, vystup=io.StringIO(),
                tovarna_modelu=lambda configuration, dry_run: (FakeModel({}), evaluator)) == 1
    raw = list((directory / "data").glob("surova_odpoved_porovnani_*.txt"))
    assert len(raw) == 1 and raw[0].read_text(encoding="utf-8") == "SUROVA-ODPOVED"


def test_cli_compare_refreshes_missing_snapshot_prompts(app_root, monkeypatch):
    """Runs created before comparison support lack saved comparison templates."""
    directory, _ = _completed_run_cli(app_root)
    snapshot = directory / "data" / "konfigurace" / "prompty"
    for p in snapshot.glob("porovnani_*.md"):
        p.unlink()
    (app_root / "prompts" / "comparison_elements.md").write_text(
        (app_root / "prompts" / "comparison_elements.md").read_text(encoding="utf-8") + "\nUPRAVENY-PROMPT\n",
        encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    evaluator = _evaluator()
    assert main(["porovnat"], koren=app_root, vystup=io.StringIO(),
                tovarna_modelu=lambda configuration, dry_run: (FakeModel({}), evaluator)) == 0
    assert "UPRAVENY-PROMPT" in dict((step, i) for step, i, _ in evaluator.calls)['comparison_elements']
    assert "UPRAVENY-PROMPT" in (snapshot / "porovnani_prvky.md").read_text(encoding="utf-8")
    # Calibration reuses the saved evaluation prompt; hodnoceni.md is not overwritten.
    (app_root / "prompts" / "evaluation.md").write_text("ZMENENY", encoding="utf-8")
    evaluator = _evaluator()
    assert main(["porovnat"], koren=app_root, vystup=io.StringIO(),
                tovarna_modelu=lambda configuration, dry_run: (FakeModel({}), evaluator)) == 0
    assert "ZMENENY" not in evaluator.calls[0][1]


def test_cli_compare_does_not_support_demo_mode(app_root):
    _completed_run_cli(app_root)
    out = io.StringIO()
    assert main(["--nanecisto", "porovnat"], koren=app_root, vystup=out) == 2
    assert "--nanecisto" in out.getvalue()


def test_calibration_html_shows_criterion_scores(tmp_path, sources):
    run, _ = _completed_run(tmp_path, sources)
    calibration = make_evaluation(7.0, suggestions=0)
    html = compare(run, sources, REFERENCE, _evaluator(comparison_calibration=[calibration]), _silent)\
        .read_text(encoding="utf-8")
    final = run.data('evaluation_1', Evaluation)
    assert final.criteria[0].score == 9.5
    assert "9,5" in html and "7,0" in html

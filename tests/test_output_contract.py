"""Freeze generated Czech paths and synthetic v1 data before the naming refactor.

A source-directory rename must not rename artifacts or make saved steps unreadable.
Legacy payloads were captured once from the original application, never rebuilt by tests.
"""
from datetime import datetime
import json
from pathlib import Path
import shutil

from refiner.application import finish_run, resume_run, open_completed_run, start_run
from refiner.run import Run
from refiner.data import Evaluation, SuggestionReview, RequirementsOutput
from refiner.models.errors import ModelError
from refiner.models.fakes import FakeModel
from refiner.comparison import (
    Coverage, ElementCoverage, ReferenceElement, ReferenceElements,
    PairComparison, CriterionComparison, compare,
)
from tests.helpers import TEST_REQUEST, make_evaluation, make_criteria, scripted_responses

FIXED_TIME = datetime(2026, 10, 17, 9, 0)
MANIFEST = json.loads((Path(__file__).parent / "fixtures/output_paths.json").read_text(encoding="utf-8"))


def _paths(directory: Path) -> set[str]:
    return {path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file()}


def _expected(*groups: str) -> set[str]:
    return {path for group in groups for path in MANIFEST[group]}


def _app_root(tmp_path: Path, repo_root: Path) -> Path:
    root = tmp_path / "app"
    root.mkdir()
    shutil.copyfile(repo_root / "settings.yaml", root / "settings.yaml")
    for directory in ("profiles", 'prompts'):
        shutil.copytree(repo_root / directory, root / directory)
    (root / "input").mkdir()
    (root / "input/poptavka.md").write_text(TEST_REQUEST, encoding="utf-8")
    (root / "input/poptavka.kriteria.yaml").write_text("vahy: {B1: 2}\n", encoding="utf-8")
    return root


def _models(interrupted: bool = False) -> tuple[FakeModel, FakeModel]:
    writer, evaluator = scripted_responses([8.0, 9.5] if interrupted else [9.5])
    for step in ('draft_1', 'draft_2'):
        writer[step][0] += "\n\nCena: [DOPLNIT: cena – sazba není v podkladech]\n"
    if interrupted:
        evaluator['evaluation_2'] = [ModelError('network', "OpenAI")]
    return FakeModel(writer, name="claude-falesny"), FakeModel(evaluator, name="gpt-falesny")


def _comparison_model() -> FakeModel:
    ids = [criterion.id for criterion in make_criteria()]
    return FakeModel({
        'comparison_calibration': [make_evaluation(9.0, suggestions=0)],
        'comparison_pair_1': [PairComparison(criteria=[
            CriterionComparison(id=id_, better="A", rationale="Zdůvodnění.") for id_ in ids])],
        'comparison_pair_2': [PairComparison(criteria=[
            CriterionComparison(id=id_, better="B", rationale="Zdůvodnění.") for id_ in ids])],
        'comparison_elements': [ReferenceElements(elements=[ReferenceElement(id="P1", description="Metodika cvičení")])],
        'comparison_coverage': [Coverage(items=[ElementCoverage(id="P1", status='present', comment="Kap. 1.")])],
    }, name="gpt-falesny")


def test_existing_output_paths_and_czech_content(tmp_path, repo_root):
    root = _app_root(tmp_path, repo_root)
    interrupted, sources = start_run(root, root / "input/poptavka.md", "nabidka", FIXED_TIME,
                                    dry_run=False)
    assert finish_run(interrupted, sources, *_models(interrupted=True), lambda _: None, None) == 1
    paths = _paths(interrupted.directory)
    assert paths == _expected("snapshots", "static", "interrupted_steps", "log")
    assert "06_navrh_v2_zmeny.html" in paths
    assert "data/konfigurace/prompty/hodnoceni.md" in paths
    assert "data/beh.json" in paths and "prehled.html" in paths
    assert "Běh byl přerušen" in (interrupted.directory / "prehled.html").read_text(encoding="utf-8")

    completed, sources = start_run(root, root / "input/poptavka.md", "nabidka", FIXED_TIME,
                                  dry_run=False)
    assert interrupted.directory.name == "2026-10-17_0900_poptavka"
    assert completed.directory.name == "2026-10-17_0900_poptavka_2"
    messages = []
    assert finish_run(completed, sources, *_models(), messages.append, None) == 0
    assert _paths(completed.directory) == _expected("snapshots", "static", "completed_steps", "final_exports", "log")
    assert "Hotovo. Přehled běhu:" in "\n".join(messages)
    final_text = (completed.directory / "FINALNI_nabidka.md").read_text(encoding="utf-8")
    assert "[DOPLNIT:" in final_text and "# Nabídka" in final_text
    assert final_text == completed.text('draft_1')
    report = (completed.directory / "prehled.html").read_text(encoding="utf-8")
    assert 'href="FINALNI_nabidka.md"' in report and 'href="FINALNI_nabidka.docx"' in report

    snapshot = completed.directory / "data/konfigurace"
    assert (snapshot / "nastaveni.yaml").read_bytes() == (root / "settings.yaml").read_bytes()
    assert (snapshot / "profil.yaml").read_bytes() == (root / "profiles/proposal.yaml").read_bytes()
    assert (snapshot / "kriteria.yaml").read_bytes() == (root / "input/poptavka.kriteria.yaml").read_bytes()
    for prompt in (root / 'prompts').glob("*.md"):
        from refiner.artifacts import PROMPT_SNAPSHOT_NAMES
        assert (snapshot / "prompty" / PROMPT_SNAPSHOT_NAMES[prompt.stem]).read_bytes() == prompt.read_bytes()

    comparison = compare(completed, sources, "# Reference\n\nMetodika cvičení.", _comparison_model(),
                         lambda _: None)
    assert comparison.name == "porovnani.html"
    assert _paths(completed.directory) == _expected(
        "snapshots", "static", "completed_steps", "final_exports", "log", "comparison")
    assert "Odpověď:" in (completed.directory / "porovnani_formular.md").read_text(encoding="utf-8")


def test_legacy_fixtures_match_current_reader(legacy_interrupted, legacy_completed):
    for directory, status, steps in (
        (legacy_interrupted, 'interrupted', "interrupted_steps"),
        (legacy_completed, 'completed', "completed_steps"),
    ):
        legacy_state = json.loads((directory / "data/beh.json").read_text(encoding="utf-8"))
        assert "schema_version" not in legacy_state
        assert legacy_state["stav"] == {"interrupted": "prerusen", "completed": "dokoncen"}[status]
        assert legacy_state["vytvoreno"] == "2026-10-17T09:00:00"
        assert legacy_state["ukonceno"] == "2026-10-17T09:00:00"
        run = Run.open(directory)
        assert run.state.status == status and run.state.dry_run is False
        assert run.text('request') == TEST_REQUEST
        assert len(run.data('requirements', RequirementsOutput).requirements) == 3
        assert run.data('evaluation_1', Evaluation).suggestions[0].priority == 'medium'
        for step in run.state.steps.values():
            assert (directory / step.file).is_file()
            if step.data:
                assert (directory / step.data).is_file()
        expected = _expected("snapshots", "static", steps)
        if status == 'completed':
            expected |= {"FINALNI_nabidka.md", "porovnani_formular.md"}
        assert _paths(directory) == expected
        assert "${poptavka}" in (directory / "data/konfigurace/prompty/navrh.md").read_text(encoding="utf-8")

    interrupted, _ = resume_run(legacy_interrupted, dry_run=False)
    assert interrupted.is_done('draft_2') and not interrupted.is_done('evaluation_2')
    assert interrupted.data('review_1', SuggestionReview).decisions[0].decision == 'accepted'
    completed, _ = open_completed_run(legacy_completed, dry_run=False)
    assert completed.state.final_version == 1
    assert "Odpověď: ano, 30 minut" in (legacy_completed / "porovnani_formular.md").read_text(encoding="utf-8")

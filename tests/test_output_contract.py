"""Freeze generated Czech paths and synthetic v1 data before the naming refactor.

A source-directory rename must not rename artifacts or make saved steps unreadable.
Legacy payloads were captured once from the original application, never rebuilt by tests.
"""
from datetime import datetime
import json
from pathlib import Path
import shutil

from refiner.aplikace import dokonci, obnov_beh, otevri_dokonceny, zahaj_beh
from refiner.beh import Beh
from refiner.data import Hodnoceni, Posouzeni, VystupNalezitosti
from refiner.models.errors import ModelError
from refiner.models.fakes import FakeModel
from refiner.porovnani import (
    Pokryti, PokrytiPrvku, PrvekReference, SeznamPrvku,
    Srovnani, SrovnaniKriteria, porovnej,
)
from tests.pomocne import POPTAVKA_TEST, hodnoceni, kriteria_test, odpovedi_skriptu

FIXED_TIME = datetime(2026, 10, 17, 9, 0)
MANIFEST = json.loads((Path(__file__).parent / "fixtures/output_paths.json").read_text(encoding="utf-8"))


def _paths(directory: Path) -> set[str]:
    return {path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file()}


def _expected(*groups: str) -> set[str]:
    return {path for group in groups for path in MANIFEST[group]}


def _app_root(tmp_path: Path, repo_root: Path) -> Path:
    root = tmp_path / "app"
    root.mkdir()
    shutil.copyfile(repo_root / "nastaveni.yaml", root / "nastaveni.yaml")
    for directory in ("profily", "prompty"):
        shutil.copytree(repo_root / directory, root / directory)
    (root / "input").mkdir()
    (root / "input/poptavka.md").write_text(POPTAVKA_TEST, encoding="utf-8")
    (root / "input/poptavka.kriteria.yaml").write_text("vahy: {B1: 2}\n", encoding="utf-8")
    return root


def _models(interrupted: bool = False) -> tuple[FakeModel, FakeModel]:
    writer, evaluator = odpovedi_skriptu([8.0, 9.5] if interrupted else [9.5])
    for step in ("navrh_1", "navrh_2"):
        writer[step][0] += "\n\nCena: [DOPLNIT: cena – sazba není v podkladech]\n"
    if interrupted:
        evaluator["hodnoceni_2"] = [ModelError('network', "OpenAI")]
    return FakeModel(writer, name="claude-falesny"), FakeModel(evaluator, name="gpt-falesny")


def _comparison_model() -> FakeModel:
    ids = [criterion.id for criterion in kriteria_test()]
    return FakeModel({
        "porovnani_kalibrace": [hodnoceni(9.0, navrhy=0)],
        "porovnani_srovnani_1": [Srovnani(kriteria=[
            SrovnaniKriteria(id=id_, lepsi="A", zduvodneni="Zdůvodnění.") for id_ in ids])],
        "porovnani_srovnani_2": [Srovnani(kriteria=[
            SrovnaniKriteria(id=id_, lepsi="B", zduvodneni="Zdůvodnění.") for id_ in ids])],
        "porovnani_prvky": [SeznamPrvku(prvky=[PrvekReference(id="P1", popis="Metodika cvičení")])],
        "porovnani_pokryti": [Pokryti(polozky=[PokrytiPrvku(id="P1", stav="je", komentar="Kap. 1.")])],
    }, name="gpt-falesny")


def test_existing_output_paths_and_czech_content(tmp_path, koren_repa):
    root = _app_root(tmp_path, koren_repa)
    interrupted, sources = zahaj_beh(root, root / "input/poptavka.md", "nabidka", FIXED_TIME,
                                    nanecisto=False)
    assert dokonci(interrupted, sources, *_models(interrupted=True), lambda _: None, None) == 1
    paths = _paths(interrupted.slozka)
    assert paths == _expected("snapshots", "static", "interrupted_steps", "log")
    assert "06_navrh_v2_zmeny.html" in paths
    assert "data/konfigurace/prompty/hodnoceni.md" in paths
    assert "data/beh.json" in paths and "prehled.html" in paths
    assert "Běh byl přerušen" in (interrupted.slozka / "prehled.html").read_text(encoding="utf-8")

    completed, sources = zahaj_beh(root, root / "input/poptavka.md", "nabidka", FIXED_TIME,
                                  nanecisto=False)
    assert interrupted.slozka.name == "2026-10-17_0900_poptavka"
    assert completed.slozka.name == "2026-10-17_0900_poptavka_2"
    messages = []
    assert dokonci(completed, sources, *_models(), messages.append, None) == 0
    assert _paths(completed.slozka) == _expected("snapshots", "static", "completed_steps", "final_exports", "log")
    assert "Hotovo. Přehled běhu:" in "\n".join(messages)
    final_text = (completed.slozka / "FINALNI_nabidka.md").read_text(encoding="utf-8")
    assert "[DOPLNIT:" in final_text and "# Nabídka" in final_text
    assert final_text == completed.text("navrh_1")
    report = (completed.slozka / "prehled.html").read_text(encoding="utf-8")
    assert 'href="FINALNI_nabidka.md"' in report and 'href="FINALNI_nabidka.docx"' in report

    snapshot = completed.slozka / "data/konfigurace"
    assert (snapshot / "nastaveni.yaml").read_bytes() == (root / "nastaveni.yaml").read_bytes()
    assert (snapshot / "profil.yaml").read_bytes() == (root / "profily/nabidka.yaml").read_bytes()
    assert (snapshot / "kriteria.yaml").read_bytes() == (root / "input/poptavka.kriteria.yaml").read_bytes()
    for prompt in (root / "prompty").glob("*.md"):
        assert (snapshot / "prompty" / prompt.name).read_bytes() == prompt.read_bytes()

    comparison = porovnej(completed, sources, "# Reference\n\nMetodika cvičení.", _comparison_model(),
                         lambda _: None)
    assert comparison.name == "porovnani.html"
    assert _paths(completed.slozka) == _expected(
        "snapshots", "static", "completed_steps", "final_exports", "log", "comparison")
    assert "Odpověď:" in (completed.slozka / "porovnani_formular.md").read_text(encoding="utf-8")


def test_legacy_fixtures_match_current_reader(legacy_interrupted, legacy_completed):
    for directory, status, steps in (
        (legacy_interrupted, "prerusen", "interrupted_steps"),
        (legacy_completed, "dokoncen", "completed_steps"),
    ):
        legacy_state = json.loads((directory / "data/beh.json").read_text(encoding="utf-8"))
        assert "schema_version" not in legacy_state
        assert legacy_state["stav"] == status
        assert legacy_state["vytvoreno"] == "2026-10-17T09:00:00"
        assert legacy_state["ukonceno"] == "2026-10-17T09:00:00"
        run = Beh.otevri(directory)
        assert run.stav.stav == status and run.stav.nanecisto is False
        assert run.text("poptavka") == POPTAVKA_TEST
        assert len(run.data("nalezitosti", VystupNalezitosti).nalezitosti) == 3
        assert run.data("hodnoceni_1", Hodnoceni).navrhy[0].priorita == "stredni"
        for step in run.stav.kroky.values():
            assert (directory / step.soubor).is_file()
            if step.data:
                assert (directory / step.data).is_file()
        expected = _expected("snapshots", "static", steps)
        if status == "dokoncen":
            expected |= {"FINALNI_nabidka.md", "porovnani_formular.md"}
        assert _paths(directory) == expected
        assert "${poptavka}" in (directory / "data/konfigurace/prompty/navrh.md").read_text(encoding="utf-8")

    interrupted, _ = obnov_beh(legacy_interrupted, nanecisto=False)
    assert interrupted.hotovo("navrh_2") and not interrupted.hotovo("hodnoceni_2")
    assert interrupted.data("posouzeni_1", Posouzeni).rozhodnuti[0].rozhodnuti == "prijato"
    completed, _ = otevri_dokonceny(legacy_completed, nanecisto=False)
    assert completed.stav.finalni_verze == 1
    assert "Odpověď: ano, 30 minut" in (legacy_completed / "porovnani_formular.md").read_text(encoding="utf-8")

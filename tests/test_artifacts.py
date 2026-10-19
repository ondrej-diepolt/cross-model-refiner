"""Keep source asset renames separate from generated Czech artifact names."""
from datetime import datetime
from pathlib import Path
import shutil

import pytest


@pytest.mark.parametrize("profile_id,token", [
    ("proposal", "nabidka"), ("nabidka", "nabidka"),
    ("policy", "smernice"), ("smernice", "smernice"), ("custom_offer", "custom_offer"),
])
def test_profile_output_token_preserves_historical_name(profile_id, token):
    from refiner.artifacts import output_profile_name

    assert output_profile_name(profile_id) == token


@pytest.mark.parametrize("profile_id,token", [
    ("proposal", "nabidka"), ("policy", "smernice"), ("custom_offer", "custom_offer"),
])
def test_new_configuration_keeps_czech_snapshots_and_final_exports(tmp_path, koren_repa, profile_id, token):
    from refiner.artifacts import PROMPT_SNAPSHOT_NAMES
    from refiner.aplikace import dokonci, zahaj_beh
    from refiner.data import sestav_kriteria
    from refiner.models.fakes import FakeModel
    from tests.pomocne import NALEZITOSTI_TEST, POPTAVKA_TEST, hodnoceni, odpovedi_skriptu

    root = tmp_path / "app"
    root.mkdir()
    shutil.copyfile(koren_repa / "settings.yaml", root / "settings.yaml")
    shutil.copytree(koren_repa / "profiles", root / "profiles")
    shutil.copytree(koren_repa / "prompty", root / "prompty")
    if profile_id == "custom_offer":
        shutil.copyfile(root / "profiles/proposal.yaml", root / "profiles/custom_offer.yaml")
    (root / "input").mkdir()
    request = root / "input/poptavka.md"
    request.write_text(POPTAVKA_TEST, encoding="utf-8")
    request.with_suffix(".criteria.yaml").write_text("weights: {}\n", encoding="utf-8")
    run, sources = zahaj_beh(root, request, profile_id, datetime(2026, 10, 17, 9, 0))
    assert sources.konfigurace.profile_id == profile_id
    assert sources.konfigurace.output_profile_name == token
    assert run.stav.profil == token
    snapshot = run.slozka / "data/konfigurace"
    assert (snapshot / "nastaveni.yaml").read_bytes() == (root / "settings.yaml").read_bytes()
    assert (snapshot / "profil.yaml").read_bytes() == (root / f"profiles/{profile_id}.yaml").read_bytes()
    assert (snapshot / "kriteria.yaml").read_bytes() == request.with_suffix(".criteria.yaml").read_bytes()
    assert set(PROMPT_SNAPSHOT_NAMES) == {
        "requirements", "draft", "evaluation", "review", "revision",
        "comparison_criteria", "comparison_elements", "comparison_coverage",
    }
    assert PROMPT_SNAPSHOT_NAMES["evaluation"] == "hodnoceni.md"
    for saved_name in PROMPT_SNAPSHOT_NAMES.values():
        assert (snapshot / "prompty" / saved_name).read_bytes() == (root / "prompty" / saved_name).read_bytes()
    criteria = sestav_kriteria(NALEZITOSTI_TEST, sources.konfigurace.profile_criteria)
    writer_responses, _ = odpovedi_skriptu([9.5])
    evaluator = FakeModel({"hodnoceni_1": [hodnoceni(9.5, kriteria=criteria, navrhy=0)]}, name="gpt-fake")
    assert dokonci(run, sources, FakeModel(writer_responses), evaluator, lambda _: None, None) == 0
    assert (run.slozka / f"FINALNI_{token}.md").is_file()
    assert (run.slozka / f"FINALNI_{token}.docx").is_file()
    assert f'href="FINALNI_{token}.md"' in (run.slozka / "prehled.html").read_text(encoding="utf-8")
    assert not (run.slozka / "data/configuration").exists()


def test_configuration_values_and_czech_profile_text_are_unchanged(koren_repa):
    from refiner.configuration import load_configuration

    current = load_configuration(koren_repa / "settings.yaml", koren_repa / "profiles/proposal.yaml")
    frozen = koren_repa / "tests/fixtures/legacy/completed/data/konfigurace"
    old = load_configuration(frozen / "nastaveni.yaml", frozen / "profil.yaml")
    assert current.settings.model_dump() == old.settings.model_dump()
    assert current.profile.model_dump() == old.profile.model_dump()

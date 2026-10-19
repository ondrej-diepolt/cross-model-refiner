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
def test_new_configuration_keeps_czech_snapshots_and_final_exports(tmp_path, repo_root, profile_id, token):
    from refiner.artifacts import PROMPT_SNAPSHOT_NAMES
    from refiner.aplikace import dokonci, zahaj_beh
    from refiner.data import build_criteria
    from refiner.models.fakes import FakeModel
    from tests.helpers import TEST_REQUIREMENTS, TEST_REQUEST, make_evaluation, scripted_responses

    root = tmp_path / "app"
    root.mkdir()
    shutil.copyfile(repo_root / "settings.yaml", root / "settings.yaml")
    shutil.copytree(repo_root / "profiles", root / "profiles")
    shutil.copytree(repo_root / 'prompts', root / 'prompts')
    if profile_id == "custom_offer":
        shutil.copyfile(root / "profiles/proposal.yaml", root / "profiles/custom_offer.yaml")
    (root / "input").mkdir()
    request = root / "input/poptavka.md"
    request.write_text(TEST_REQUEST, encoding="utf-8")
    request.with_suffix(".criteria.yaml").write_text("weights: {}\n", encoding="utf-8")
    run, sources = zahaj_beh(root, request, profile_id, datetime(2026, 10, 17, 9, 0))
    assert sources.configuration.profile_id == profile_id
    assert sources.configuration.output_profile_name == token
    assert run.state.output_profile_name == token
    snapshot = run.directory / "data/konfigurace"
    assert (snapshot / "nastaveni.yaml").read_bytes() == (root / "settings.yaml").read_bytes()
    assert (snapshot / "profil.yaml").read_bytes() == (root / f"profiles/{profile_id}.yaml").read_bytes()
    assert (snapshot / "kriteria.yaml").read_bytes() == request.with_suffix(".criteria.yaml").read_bytes()
    assert set(PROMPT_SNAPSHOT_NAMES) == {
        "requirements", "draft", "evaluation", "review", "revision",
        "comparison_criteria", "comparison_elements", "comparison_coverage",
    }
    assert PROMPT_SNAPSHOT_NAMES["evaluation"] == "hodnoceni.md"
    for name, saved_name in PROMPT_SNAPSHOT_NAMES.items():
        assert (snapshot / "prompty" / saved_name).read_bytes() == (root / "prompts" / f"{name}.md").read_bytes()
    criteria = build_criteria(TEST_REQUIREMENTS, sources.configuration.profile_criteria)
    writer_responses, _ = scripted_responses([9.5])
    evaluator = FakeModel({'evaluation_1': [make_evaluation(9.5, criteria=criteria, suggestions=0)]}, name="gpt-fake")
    assert dokonci(run, sources, FakeModel(writer_responses), evaluator, lambda _: None, None) == 0
    assert (run.directory / f"FINALNI_{token}.md").is_file()
    assert (run.directory / f"FINALNI_{token}.docx").is_file()
    assert f'href="FINALNI_{token}.md"' in (run.directory / "prehled.html").read_text(encoding="utf-8")
    assert not (run.directory / "data/configuration").exists()


def test_configuration_values_and_czech_profile_text_are_unchanged(repo_root):
    from refiner.configuration import load_configuration

    current = load_configuration(repo_root / "settings.yaml", repo_root / "profiles/proposal.yaml")
    frozen = repo_root / "tests/fixtures/legacy/completed/data/konfigurace"
    old = load_configuration(frozen / "nastaveni.yaml", frozen / "profil.yaml")
    assert current.settings.model_dump() == old.settings.model_dump()
    assert current.profile.model_dump() == old.profile.model_dump()

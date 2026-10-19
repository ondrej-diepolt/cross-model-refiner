import json
from datetime import datetime

from refiner.run import Run
from refiner.data import Evaluation, TokenUsage, ScoreResult, RequirementsOutput

T = datetime(2026, 10, 17, 14, 32)


def test_directory_name_removes_accents(tmp_path):
    b = Run.new(tmp_path, "Národní rozvojová banka", "proposal", T)
    assert b.directory.name == "2026-10-17_1432_narodni-rozvojova-banka" and (b.directory / "data").is_dir()


def test_directory_collision_adds_suffix(tmp_path):
    b1 = Run.new(tmp_path, "Banka.md", "proposal", T)
    b2 = Run.new(tmp_path, "Banka.md", "proposal", T)
    b3 = Run.new(tmp_path, "Banka.md", "proposal", T)
    assert b1.directory.name == "2026-10-17_1432_banka"
    assert b2.directory.name == "2026-10-17_1432_banka_2"
    assert b3.directory.name == "2026-10-17_1432_banka_3"


def test_steps_numbered_in_creation_order(tmp_path):
    b = Run.new(tmp_path, "x.md", "proposal", T)
    b.write('request', "poptavka.md", "x")
    b.write('requirements', "nalezitosti.md", "y", data=RequirementsOutput(requirements=[]))
    p = b.write('draft_1', "navrh_v1.md", "z")
    d = b.write_for_step('draft_1', "navrh_v1_zmeny.html", "<p>")
    assert p.name == "03_navrh_v1.md" and d.name == "03_navrh_v1_zmeny.html"
    assert (b.directory / "data" / "02_nalezitosti.json").exists()
    assert b.text('draft_1') == "z"


def test_dry_run_mode_is_persisted(tmp_path):
    assert Run.open(Run.new(tmp_path, "a.md", "proposal", T, dry_run=True).directory).state.dry_run
    assert not Run.open(Run.new(tmp_path, "b.md", "proposal", T).directory).state.dry_run


def test_missing_mode_defaults_to_live_run(tmp_path):
    b = Run.new(tmp_path, "x.md", "proposal", T)
    file = b.directory / "data" / "beh.json"
    state = json.loads(file.read_text(encoding="utf-8"))
    del state['dry_run']
    file.write_text(json.dumps(state), encoding="utf-8")
    assert Run.open(b.directory).state.dry_run is False


def test_open_restores_state_and_data(tmp_path):
    b = Run.new(tmp_path, "x.md", "proposal", T)
    h = Evaluation(criteria=[], fabricated_facts=[], claims_to_verify=[], suggestions=[], overall_comment="ok")
    b.write('evaluation_1', "hodnoceni_v1.md", "text", data=h)
    b2 = Run.open(b.directory)
    assert b2.is_done('evaluation_1') and not b2.is_done("jine")
    assert b2.data('evaluation_1', Evaluation) == h
    assert b2.text('evaluation_1') == "text"
    assert b2.state.input == "x.md" and b2.state.created_at == T


def test_state_saved_after_each_write(tmp_path):
    b = Run.new(tmp_path, "x.md", "proposal", T)
    b.write('request', "poptavka.md", "x")
    state = json.loads((b.directory / "data" / "beh.json").read_text(encoding="utf-8"))
    assert 'request' in state['steps']


def test_atomic_save_leaves_no_temporary_file(tmp_path):
    b = Run.new(tmp_path, "x.md", "proposal", T)
    b.save()
    assert (b.directory / "data" / "beh.json").exists()
    assert not (b.directory / "data" / "beh.json.tmp").exists()


def test_finish_interrupted(tmp_path):
    b = Run.new(tmp_path, "x.md", "proposal", T)
    b.finish('interrupted', reason='error', error="boom")
    b2 = Run.open(b.directory)
    assert b2.state.status == 'interrupted' and b2.state.error == "boom" and b2.state.ended_at is not None


def test_usage_warnings_and_scores_are_persisted(tmp_path):
    b = Run.new(tmp_path, "x.md", "proposal", T)
    s = TokenUsage(step="a", model="m", input_tokens=1, output_tokens=2)
    b.add_usage([s])
    b.add_usage([s])
    b.add_warning("pozor")
    v = ScoreResult(a=1, b=1, c=1, total=1, target_met=True, unmet_reasons=[])
    b.save_score(1, v)
    b2 = Run.open(b.directory)
    assert len(b2.state.usage) == 2 and b2.state.warnings == ["pozor"]
    assert b2.state.scores["1"] == v


def test_write_fixed_path(tmp_path):
    b = Run.new(tmp_path, "x.md", "proposal", T)
    p = b.write_fixed("prehled.html", "<p>")
    q = b.write_fixed("data/konfigurace/a.bin", b"\x00")
    assert p.read_text(encoding="utf-8") == "<p>" and q.read_bytes() == b"\x00"

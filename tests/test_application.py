import shutil
from datetime import datetime
from pathlib import Path

import pytest

import refiner.application as application
from refiner.application import finish_run, find_latest_run, resume_run, open_completed_run, start_run
from refiner.run import Run
from refiner.models.errors import ModelError
from refiner.models.fakes import FakeModel
from refiner.input import InputError
from tests.helpers import TEST_REQUEST, make_evaluation, scripted_responses, scripted_models

T = datetime(2026, 10, 17, 9, 0)


@pytest.fixture
def root(tmp_path, repo_root) -> Path:
    """Temporary app root with settings, profiles, prompts, and a request."""
    k = tmp_path / "app"
    k.mkdir()
    shutil.copy(repo_root / "settings.yaml", k / "settings.yaml")
    shutil.copytree(repo_root / "profiles", k / "profiles")
    shutil.copytree(repo_root / 'prompts', k / 'prompts')
    (k / "input").mkdir()
    (k / "input" / "poptavka.md").write_text(TEST_REQUEST, encoding="utf-8")
    return k


def _start(root: Path, now: datetime = T):
    return start_run(root, root / "input" / "poptavka.md", "nabidka", now)


# ---------------------------------------------------------------- start and resume

def test_start_run_copies_configuration_and_request(root):
    (root / 'materials').mkdir()
    (root / 'materials' / "profil_firmy.md").write_text("Firma Alfa s.r.o.", encoding="utf-8")
    (root / "input" / "poptavka.kriteria.yaml").write_text("vahy: {B1: 2}\n", encoding="utf-8")

    run, z = _start(root)

    assert run.directory.parent == root / "output"
    assert (run.directory / "01_poptavka.md").exists()
    assert (run.directory / "01_poptavka.md").read_text(encoding="utf-8") == TEST_REQUEST
    configuration = run.directory / "data" / "konfigurace"
    assert (configuration / "prompty" / "navrh.md").exists()
    assert (configuration / "nastaveni.yaml").exists()
    assert (configuration / "profil.yaml").read_text(encoding="utf-8") == \
        (root / "profiles" / "proposal.yaml").read_text(encoding="utf-8")
    assert (configuration / "kriteria.yaml").exists()
    assert z.prompts == run.directory / "data" / "konfigurace" / "prompty"
    assert z.request == TEST_REQUEST
    assert "Firma Alfa s.r.o." in z.materials
    assert "Firma Alfa s.r.o." in (run.directory / "data" / "podklady.md").read_text(encoding="utf-8")
    assert z.configuration.profile_id == "proposal"
    assert {k.id: k.weight for k in z.configuration.profile_criteria}["B1"] == 2
    assert run.state.output_profile_name == "nabidka" and run.state.input == "poptavka.md"


def test_start_run_without_criteria_or_materials(root):
    run, z = _start(root)
    assert not (run.directory / "data" / "konfigurace" / "kriteria.yaml").exists()
    assert z.materials == ""
    assert (run.directory / "data" / "podklady.md").read_text(encoding="utf-8") == ""


def test_start_run_crlf_input_does_not_duplicate_lines(root):
    (root / "input" / "poptavka.md").write_bytes(b"# Popt\r\n\r\nText.\r\n")
    (root / 'materials').mkdir()
    (root / 'materials' / "profil.md").write_bytes(b"Firma\r\nIC\r\n")
    run, z = _start(root)
    assert z.request == "# Popt\n\nText.\n"
    assert run.text('request') == "# Popt\n\nText.\n"
    assert "Firma\nIC" in z.materials and "\r" not in z.materials


def test_resume_uses_saved_configuration(root):
    run, _ = _start(root)
    settings = root / "settings.yaml"
    settings.write_text(settings.read_text(encoding="utf-8").replace("max_revisions: 3", "max_revisions: 1"),
                         encoding="utf-8")
    (root / "prompts" / "draft.md").write_text("ZMĚNĚNO", encoding="utf-8")

    reopened, z2 = resume_run(run.directory)

    assert reopened.directory == run.directory
    assert z2.configuration.settings.loop.max_revisions == 3
    assert z2.prompts == run.directory / "data" / "konfigurace" / "prompty"
    assert (z2.prompts / "navrh.md").read_text(encoding="utf-8") != "ZMĚNĚNO"
    assert z2.configuration.profile_id == "proposal"
    assert z2.request == TEST_REQUEST
    # Resume must not rewrite completed step records.
    assert list(reopened.state.steps) == ['request'] and reopened.state.steps['request'].number == 1


def _edit(file: Path, *replacements: tuple[str, str]) -> None:
    text = file.read_text(encoding="utf-8")
    for a, b in replacements:
        assert a in text
        text = text.replace(a, b)
    file.write_text(text, encoding="utf-8")


def test_resume_loads_repository_models_and_prices(root):
    run, _ = _start(root)
    _edit(root / "settings.yaml",
           ("max_tokens_json: 32000", "max_tokens_json: 50000"),
           ("max_output_tokens: 64000", "max_output_tokens: 99000"),
           ("claude-opus-5-5: {input: 4.0", "claude-opus-5-5: {input: 7.0"),
           ("max_revisions: 3", "max_revisions: 1"))
    (root / "prompts" / "draft.md").write_text("ZMĚNĚNO", encoding="utf-8")
    messages: list[str] = []

    _, z = resume_run(run.directory, root=root, report=messages.append)

    n = z.configuration.settings
    assert n.models.claude.max_tokens_json == 50000 and n.models.gpt.max_output_tokens == 99000
    assert n.prices_usd_per_million["claude-opus-5-5"].input == 7.0
    # Saved loop settings, profile, and prompts keep scores reproducible.
    assert n.loop.max_revisions == 3
    assert (z.prompts / "navrh.md").read_text(encoding="utf-8") != "ZMĚNĚNO"
    log = (run.directory / "data" / "beh.log").read_text(encoding="utf-8")
    assert "models" in log and "settings.yaml" in log and "snapshot" in log
    # The configuration snapshot stays unchanged.
    assert "max_tokens_json: 32000" in (run.directory / "data" / "konfigurace" / "nastaveni.yaml") \
        .read_text(encoding="utf-8")


@pytest.mark.parametrize("corrupt", ["delete", "invalid"])
def test_resume_invalid_repository_settings_uses_snapshot(root, corrupt):
    run, _ = _start(root)
    settings = root / "settings.yaml"
    if corrupt == "delete":
        settings.unlink()
    else:
        _edit(settings, ("effort: high", "effort: hihg"))
    messages: list[str] = []

    _, z = resume_run(run.directory, root=root, report=messages.append)

    assert z.configuration.settings.models.claude.max_tokens_json == 32000
    assert any("Varování" in h and "kopie" in h for h in messages)
    log = (run.directory / "data" / "beh.log").read_text(encoding="utf-8")
    assert "WARNING" in log and "settings.yaml" in log


def test_resume_mode_must_match(root):
    run, _ = _start(root)
    with pytest.raises(InputError, match="--dry-run"):
        resume_run(run.directory, dry_run=True)
    demo, _ = start_run(root, root / "input" / "poptavka.md", "nabidka", T, dry_run=True)
    assert demo.state.dry_run
    with pytest.raises(InputError, match="ukázkový"):
        resume_run(demo.directory, dry_run=False)
    assert resume_run(demo.directory, dry_run=True)[0].directory == demo.directory


def test_comparison_rejects_demo_run(root):
    demo, z = start_run(root, root / "input" / "poptavka.md", "nabidka", T, dry_run=True)
    assert finish_run(demo, z, *scripted_models([9.5]), report=lambda _: None, template=None) == 0
    with pytest.raises(InputError, match="ukázkový"):
        open_completed_run(demo.directory, dry_run=False)


def test_resume_rejects_completed_run(root):
    run, z = _start(root)
    assert finish_run(run, z, *scripted_models([9.5]), report=lambda _: None, template=None) == 0
    with pytest.raises(InputError, match="je už dokončený"):
        resume_run(run.directory)


def test_resume_rejects_non_run_directory(tmp_path):
    with pytest.raises(InputError):
        resume_run(tmp_path)


# ---------------------------------------------------------------- completion

def test_finish_run_success(root):
    run, z = _start(root)
    out: list[str] = []
    assert finish_run(run, z, *scripted_models([9.5]), report=out.append, template=None) == 0
    assert (run.directory / "FINALNI_nabidka.docx").exists() and (run.directory / "prehled.html").exists()
    assert (run.directory / "FINALNI_nabidka.md").read_text(encoding="utf-8") == \
        (run.directory / "03_navrh_v1.md").read_text(encoding="utf-8")
    state = Run.open(run.directory).state
    assert state.status == 'completed' and state.stop_reason == 'target_reached' and state.final_version == 1
    assert state.error is None
    assert any(str(run.directory / "prehled.html") in r for r in out)


def test_api_error_saves_interrupted_run(root):
    run, z = _start(root)
    writer, _ = scripted_models([9.5])
    evaluator = FakeModel({'evaluation_1': [ModelError('credit', "OpenAI")]}, name="gpt-falesny")
    out: list[str] = []
    assert finish_run(run, z, writer, evaluator, report=out.append, template=None) == 1
    state = Run.open(run.directory).state
    assert state.status == 'interrupted' and "kredit" in state.error and (run.directory / "03_navrh_v1.md").exists()
    report = "\n".join(out)
    assert "resume.bat" in report and (run.directory / "prehled.html").exists()
    assert "Došel kredit u OpenAI" in report and str(run.directory) in report
    assert "Běh byl přerušen" in (run.directory / "prehled.html").read_text(encoding="utf-8")
    assert "ModelError" in (run.directory / "data" / "beh.log").read_text(encoding="utf-8")


def test_raw_response_is_saved(root):
    run, z = _start(root)
    writer, _ = scripted_models([9.5])
    # Invalid step output gets one repair; the second failure stops the step.
    error = ModelError('invalid_output', "OpenAI", raw_response="{rozbite")
    evaluator = FakeModel({'evaluation_1': [error, error]}, name="gpt-falesny")
    assert finish_run(run, z, writer, evaluator, report=lambda _: None, template=None) == 1
    files = list((run.directory / "data").glob("surova_odpoved_*.txt"))
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8") == "{rozbite"


def test_invalid_response_usage_is_saved(root):
    # Both evaluator responses incur usage, but score 9.8 fails validation.
    run, z = _start(root)
    writer, _ = scripted_models([9.5])
    invalid = make_evaluation(8.0, overrides={"B1": 9.8})
    evaluator = FakeModel({'evaluation_1': [invalid, invalid]}, name="gpt-falesny")
    assert finish_run(run, z, writer, evaluator, report=lambda _: None, template=None) == 1
    state = Run.open(run.directory).state
    assert [s.step for s in state.usage if s.model == "gpt-falesny"] == ['evaluation_1', 'evaluation_1']
    assert len((list((run.directory / "data").glob("surova_odpoved_*.txt")))) == 1


def test_ctrl_c_saves_interrupted_run(root):
    run, z = _start(root)
    writer_responses, evaluator_responses = scripted_responses([9.5])
    writer_responses['draft_1'] = [KeyboardInterrupt(), *writer_responses['draft_1']]
    writer = FakeModel(writer_responses, name="claude-falesny")
    evaluator = FakeModel(evaluator_responses, name="gpt-falesny")
    out: list[str] = []

    assert finish_run(run, z, writer, evaluator, report=out.append, template=None) == 1
    state = Run.open(run.directory).state
    assert state.status == 'interrupted' and "Ctrl+C" in state.error
    assert "resume.bat" in "\n".join(out)
    assert (run.directory / "02_nalezitosti.md").exists() and not (run.directory / "03_navrh_v1.md").exists()

    reopened, z2 = resume_run(run.directory)
    assert finish_run(reopened, z2, writer, evaluator, report=out.append, template=None) == 0
    state = Run.open(run.directory).state
    assert state.status == 'completed' and state.error is None
    assert (run.directory / "03_navrh_v1.md").exists() and (run.directory / "FINALNI_nabidka.docx").exists()
    assert [k for k, v in state.steps.items() if v.number == 2] == ['requirements']


def test_unexpected_exception(root):
    run, z = _start(root)
    writer = FakeModel({'requirements': [ZeroDivisionError("deleni nulou")]}, name="claude-falesny")
    _, evaluator = scripted_models([9.5])
    out: list[str] = []
    assert finish_run(run, z, writer, evaluator, report=out.append, template=None) == 1
    state = Run.open(run.directory).state
    assert state.status == 'interrupted' and "Neočekávaná chyba" in state.error
    assert "Neočekávaná chyba" in "\n".join(out)
    log = (run.directory / "data" / "beh.log").read_text(encoding="utf-8")
    assert "Traceback" in log and "ZeroDivisionError" in log


def test_overview_failure_preserves_original_error(root, monkeypatch):
    def broken(*_a, **_k):
        raise RuntimeError("šablona přehledu je rozbitá")

    monkeypatch.setattr(application, "create_overview", broken)
    run, z = _start(root)
    writer, _ = scripted_models([9.5])
    evaluator = FakeModel({'evaluation_1': [ModelError('credit', "OpenAI")]}, name="gpt-falesny")
    out: list[str] = []
    assert finish_run(run, z, writer, evaluator, report=out.append, template=None) == 1
    state = Run.open(run.directory).state
    assert state.status == 'interrupted' and "kredit" in state.error
    assert "Došel kredit" in "\n".join(out)
    assert "šablona přehledu je rozbitá" in (run.directory / "data" / "beh.log").read_text(encoding="utf-8")


def test_docx_failure_is_warning(root, monkeypatch):
    def broken(*_a, **_k):
        raise OSError("pandoc nenalezen")

    monkeypatch.setattr(application, "export_docx", broken)
    run, z = _start(root)
    assert finish_run(run, z, *scripted_models([9.5]), report=lambda _: None, template=None) == 0
    state = Run.open(run.directory).state
    assert state.status == 'completed'
    assert any("DOCX" in v and "pandoc nenalezen" in v for v in state.warnings)
    assert (run.directory / "FINALNI_nabidka.md").exists()
    assert not (run.directory / "FINALNI_nabidka.docx").exists()


def test_log_handler_detached_after_completion(root):
    import logging

    run, z = _start(root)
    before = list(logging.getLogger("refiner").handlers)
    finish_run(run, z, *scripted_models([9.5]), report=lambda _: None, template=None)
    assert logging.getLogger("refiner").handlers == before
    # Closed file handles allow deletion on Windows.
    (run.directory / "data" / "beh.log").unlink()


# ---------------------------------------------------------------- latest-run discovery

def test_find_latest_interrupted_run(root):
    output = root / "output"
    assert find_latest_run(output, {'interrupted', 'running'}) is None

    old, _ = _start(root, datetime(2026, 10, 17, 8, 0))
    old.finish('interrupted', error="x")
    new, _ = _start(root, datetime(2026, 10, 17, 10, 0))
    new.finish('interrupted', error="x")
    completed, _ = _start(root, datetime(2026, 10, 17, 11, 0))
    completed.finish('completed', 'target_reached', final_version=1)
    (output / "random_directory").mkdir()
    (output / "broken").mkdir()
    (output / "broken" / "data").mkdir()
    (output / "broken" / "data" / "beh.json").write_text("{", encoding="utf-8")

    assert find_latest_run(output, {'interrupted', 'running'}) == new.directory
    assert find_latest_run(output, {'completed'}) == completed.directory
    assert find_latest_run(output, {'running'}) is None


def test_find_latest_run_skips_other_mode(root):
    output = root / "output"
    live, _ = _start(root, datetime(2026, 10, 17, 8, 0))
    live.finish('interrupted', error="x")
    demo, _ = start_run(root, root / "input" / "poptavka.md", "nabidka",
                        datetime(2026, 10, 17, 10, 0), dry_run=True)
    demo.finish('interrupted', error="x")
    assert find_latest_run(output, {'interrupted'}) == demo.directory
    assert find_latest_run(output, {'interrupted'}, dry_run=False) == live.directory
    assert find_latest_run(output, {'interrupted'}, dry_run=True) == demo.directory

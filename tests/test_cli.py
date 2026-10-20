import io
import os
import shutil
from pathlib import Path

import pytest

from refiner.run import Run
from refiner.cli import main
from refiner.steps import extract_requirements
from refiner.models.errors import ModelError
from refiner.models.fakes import FakeModel, demo_models
from tests.helpers import TEST_REQUEST


@pytest.mark.parametrize("option", ["--dry-run", "--nanecisto"])
def test_dry_run_aliases_complete_with_identical_calls(root, option):
    from tests.helpers import scripted_models

    writer, evaluator = scripted_models([9.5])
    modes = []
    def factory(configuration, dry_run):
        modes.append(dry_run)
        return writer, evaluator
    out = io.StringIO()
    assert main([option], root=root, input_fn=lambda _: "1", output=out, model_factory=factory) == 0
    run = _only_run(root)
    assert modes == [True] and run.state.dry_run
    assert [step for step, *_ in writer.calls] == ["requirements", "draft_1"]
    assert [step for step, *_ in evaluator.calls] == ["evaluation_1"]
    assert "Hotovo. Přehled běhu:" in out.getvalue()
    assert (run.directory / "FINALNI_nabidka.docx").is_file()
    assert (run.directory / "data/konfigurace/prompty/navrh.md").read_bytes() == (root / "prompts/draft.md").read_bytes()


@pytest.mark.parametrize("option", ["--resume", "--pokracovat"])
def test_resume_aliases_reuse_recorded_steps(root, option):
    from tests.helpers import make_evaluation

    directory = _interrupted_demo(root)
    writer = FakeModel({})
    evaluator = FakeModel({"evaluation_1": [make_evaluation(9.5)]}, name="gpt-fake")
    out = io.StringIO()
    assert main(["--nanecisto", option, str(directory)], root=root, input_fn=_forbid_input, output=out,
                model_factory=lambda configuration, dry_run: (writer, evaluator)) == 0
    assert writer.calls == [] and [step for step, *_ in evaluator.calls] == ["evaluation_1"]
    assert Run.open(directory).state.status == "completed"


@pytest.mark.parametrize("arguments", [
    ["--dry-run", "compare"], ["--nanecisto", "compare"],
    ["--resume", "saved-run", "compare"], ["--pokracovat", "saved-run", "porovnat"],
])
def test_compare_rejects_incompatible_options_with_czech_guidance(root, arguments):
    out = io.StringIO()
    assert main(arguments, root=root, input_fn=_forbid_input, output=out) == 2
    assert "nejde kombinovat" in out.getvalue()


@pytest.mark.parametrize("profile_id,token", [("proposal", "nabidka"), ("policy", "smernice"), ("custom_offer", "custom_offer")])
def test_english_cli_profiles_preserve_final_output_tokens(root, profile_id, token):
    from tests.helpers import TEST_REQUIREMENTS, scripted_responses, make_evaluation
    from refiner.data import build_criteria

    profiles = root / "profiles"
    if profile_id == "custom_offer":
        shutil.copyfile(profiles / "proposal.yaml", profiles / "custom_offer.yaml")
    for path in profiles.glob("*.yaml"):
        if path.stem != profile_id:
            path.unlink()
    def factory(configuration, dry_run):
        writer, _ = scripted_responses([9.5])
        criteria = build_criteria(TEST_REQUIREMENTS, configuration.profile_criteria)
        return FakeModel(writer), FakeModel({"evaluation_1": [make_evaluation(9.5, criteria=criteria, suggestions=0)]})
    assert main(["--dry-run"], root=root, input_fn=_forbid_input, output=io.StringIO(), model_factory=factory) == 0
    run = _only_run(root)
    assert run.state.profile_id == profile_id and run.state.output_profile_name == token
    assert (run.directory / f"FINALNI_{token}.docx").is_file()
    assert f'href="FINALNI_{token}.md"' in (run.directory / "prehled.html").read_text(encoding="utf-8")


@pytest.fixture
def root(tmp_path, repo_root) -> Path:
    """Temporary app root without .env, including settings, profiles, prompts, and a request."""
    k = tmp_path / "app"
    k.mkdir()
    shutil.copy(repo_root / "settings.yaml", k / "settings.yaml")
    shutil.copytree(repo_root / "profiles", k / "profiles")
    shutil.copytree(repo_root / 'prompts', k / 'prompts')
    (k / "input").mkdir()
    (k / "input" / "poptavka.md").write_text(TEST_REQUEST, encoding="utf-8")
    return k


def _answers(*values: str):
    queue = list(values)
    return lambda _: queue.pop(0)


def _only_run(root: Path) -> Run:
    directories = list((root / "output").iterdir())
    assert len(directories) == 1
    return Run.open(directories[0])


class _UnexpectedInput(BaseException):
    """BaseException escapes the CLI catch-all so unexpected input cannot silently pass."""


def _forbid_input(_):
    raise _UnexpectedInput("vstup_fn se neměl volat")


# ---------------------------------------------------------------- full run

def test_dry_run_completes(root):
    out = io.StringIO()
    assert main(["--nanecisto"], root=root, input_fn=lambda _: "1", output=out) == 0
    directory = next((root / "output").iterdir())
    assert (directory / "prehled.html").exists() and (directory / "FINALNI_nabidka.docx").exists()
    assert "Hotovo. Přehled běhu:" in out.getvalue()


def test_demo_scores_increase_through_full_loop(root):
    assert main(["--nanecisto"], root=root, input_fn=lambda _: "1", output=io.StringIO()) == 0
    run = _only_run(root)
    assert run.state.status == 'completed'
    assert [run.state.scores[str(k)].total for k in range(1, 5)] == [7.9, 8.7, 9.2, 9.6]
    assert run.state.stop_reason == 'target_reached'
    review = (run.directory / "05_posouzeni_1.md").read_text(encoding="utf-8")
    assert "odmít" in review.lower()
    final = (run.directory / "FINALNI_nabidka.md").read_text(encoding="utf-8")
    assert "[DOPLNIT:" in final


def test_demo_request_without_bullets(root):
    (root / "input" / "poptavka.md").write_text(
        "Poptáváme zpracování analýzy rizik.\n\nTermín dodání je do konce roku.\n", encoding="utf-8")
    assert main(["--nanecisto"], root=root, input_fn=lambda _: "1", output=io.StringIO()) == 0
    assert _only_run(root).state.status == 'completed'


def test_demo_requirements_cite_request_bullets(sources):
    writer, evaluator = demo_models()
    assert evaluator.name.startswith("gpt") and not writer.name.startswith("gpt")
    requirements, warnings = extract_requirements(writer, sources)
    assert warnings == []
    assert [n.citation for n in requirements] == [
        "popis metodiky cvičení", "harmonogram a hlavní milníky realizace", "cenu za celé plnění"]
    assert [n.id for n in requirements] == ["N1", "N2", "N3"]


def test_reporting_handles_cp1250_console(root):
    buf = io.BytesIO()
    console = io.TextIOWrapper(buf, encoding="cp1250", errors="strict")
    assert main(["--nanecisto"], root=root, input_fn=lambda _: "1", output=console) == 0
    assert "Hotovo" in buf.getvalue().decode("utf-8", errors="replace")


class _UnconfigurableStream(io.StringIO):
    """Stream without reconfigure that only supports cp1250, matching an old console."""

    encoding = "cp1250"

    def write(self, s):
        s.encode("cp1250")
        return super().write(s)


def test_reporting_handles_stream_without_reconfigure(root):
    out = _UnconfigurableStream()
    assert main(["--nanecisto"], root=root, input_fn=lambda _: "1", output=out) == 0
    assert "Hotovo" in out.getvalue()


# ---------------------------------------------------------------- input and configuration errors

def _api_mode(root: Path) -> None:
    settings = root / "settings.yaml"
    text = settings.read_text(encoding="utf-8")
    assert "mode: subscription" in text
    settings.write_text(text.replace("mode: subscription", "mode: api"), encoding="utf-8")


def test_missing_api_key(root):
    _api_mode(root)
    out = io.StringIO()
    assert main([], root=root, input_fn=_forbid_input, output=out) == 2
    assert "ANTHROPIC_API_KEY" in out.getvalue() and ".env.example" in out.getvalue()
    assert not (root / "output").exists() or not any((root / "output").iterdir())


def test_missing_openai_key(root, monkeypatch):
    _api_mode(root)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-klic")
    out = io.StringIO()
    assert main([], root=root, input_fn=_forbid_input, output=out) == 2
    assert "OPENAI_API_KEY" in out.getvalue() and "ANTHROPIC_API_KEY" not in out.getvalue()


def test_key_from_env_file(root):
    _api_mode(root)
    (root / ".env").write_text("ANTHROPIC_API_KEY=a\nOPENAI_API_KEY=b\n", encoding="utf-8")
    used = []

    def model_factory(configuration, dry_run):
        used.append(dry_run)
        return demo_models()

    out = io.StringIO()
    try:
        assert main([], root=root, input_fn=lambda _: "1", output=out, model_factory=model_factory) == 0
    finally:   # Prevent dotenv test credentials leaking into later tests.
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)
    assert used == [False]


def test_subscription_does_not_require_keys(root):
    out = io.StringIO()
    assert main([], root=root, input_fn=lambda _: "1", output=out,
                model_factory=lambda configuration, dry_run: demo_models()) == 0
    assert "ANTHROPIC_API_KEY" not in out.getvalue() and "OPENAI_API_KEY" not in out.getvalue()


def test_compare_api_mode_checks_only_openai_key(root):
    _api_mode(root)
    out = io.StringIO()
    assert main(["porovnat"], root=root, input_fn=_forbid_input, output=out) == 2
    assert "OPENAI_API_KEY" in out.getvalue() and "ANTHROPIC_API_KEY" not in out.getvalue()


def _configuration_with_mode(sources, mode):
    settings = sources.configuration.settings
    models = settings.models.model_copy(update={"mode": mode})
    return sources.configuration.__class__(
        settings.model_copy(update={"models": models}), sources.configuration.profile,
        sources.configuration.profile_id, sources.configuration.profile_criteria, sources.configuration.output_profile_name)


def test_default_factory_uses_selected_mode(sources, monkeypatch):
    import refiner.cli as cli

    for name in ("ClaudeCliModel", "CodexModel", "ClaudeModel", "GptModel"):
        monkeypatch.setattr(cli, name, type(name, (), {"__init__": lambda self, *a, **k: None}))

    def types(pair):
        return tuple(type(m).__name__ for m in pair)

    subscription = _configuration_with_mode(sources, "subscription")
    api = _configuration_with_mode(sources, "api")
    assert types(cli._default_model_factory(subscription, False)) == ("ClaudeCliModel", "CodexModel")
    assert types(cli._default_model_factory(api, False)) == ("ClaudeModel", "GptModel")
    assert type(cli._default_evaluator(subscription)).__name__ == "CodexModel"
    assert type(cli._default_evaluator(api)).__name__ == "GptModel"
    assert cli._default_model_factory(subscription, True)[1].name.startswith("gpt")   # demo models


def test_unavailable_subscription_tool_returns_2(root, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    out = io.StringIO()
    assert main([], root=root, input_fn=lambda _: "1", output=out) == 2
    assert "příkaz claude nebyl nalezen" in out.getvalue()
    assert not (root / "output").exists() or not any((root / "output").iterdir())


def test_invalid_mode_returns_2(root):
    settings = root / "settings.yaml"
    settings.write_text(settings.read_text(encoding="utf-8").replace("mode: subscription", "mode: xyz"),
                         encoding="utf-8")
    out = io.StringIO()
    assert main([], root=root, input_fn=_forbid_input, output=out) == 2
    assert "models.mode" in out.getvalue()
    assert not (root / "output").exists() or not any((root / "output").iterdir())


def test_demo_needs_no_provider_tools(root, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    assert main(["--nanecisto"], root=root, input_fn=lambda _: "1", output=io.StringIO()) == 0


@pytest.mark.parametrize("encoding", ["cp1250", "utf-16"])
def test_env_invalid_encoding_returns_2(root, encoding):
    (root / ".env").write_text("# Klíče k API\nANTHROPIC_API_KEY=a\nOPENAI_API_KEY=b\n",
                                encoding=encoding)
    out = io.StringIO()
    try:
        assert main([], root=root, input_fn=_forbid_input, output=out) == 2
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)
    assert "Soubor .env nelze přečíst" in out.getvalue() and "UTF-8" in out.getvalue()
    assert not (root / "output").exists()


def test_unexpected_input_is_not_swallowed(root):
    """An unexpected input prompt must escape the general exception handler."""
    (root / "input" / "druha.md").write_text(TEST_REQUEST, encoding="utf-8")
    with pytest.raises(_UnexpectedInput):
        main(["--nanecisto"], root=root, input_fn=_forbid_input, output=io.StringIO())


def test_empty_input_directory(root):
    (root / "input" / "poptavka.md").unlink()
    out = io.StringIO()
    assert main(["--nanecisto"], root=root, input_fn=_forbid_input, output=out) == 2
    assert "Ve složce input/ není žádná poptávka (DOCX, MD nebo TXT)." in out.getvalue()


def test_select_from_multiple_inputs(root):
    (root / "input" / "poptavka.md").rename(root / "input" / "a_jina.md")
    (root / "input" / "a_jina.md").write_text("# Jiná\n\n- jiný požadavek\n", encoding="utf-8")
    (root / "input" / "b_poptavka.md").write_text(TEST_REQUEST, encoding="utf-8")
    out = io.StringIO()
    # Retry invalid 9; select file 2 (b_poptavka.md), then profile 1 (proposal).
    assert main(["--nanecisto"], root=root, input_fn=_answers("9", "2", "1"), output=out) == 0
    assert _only_run(root).state.input == "b_poptavka.md"
    assert "1) a_jina.md" in out.getvalue() and "2) b_poptavka.md" in out.getvalue()
    assert "Neplatná volba" in out.getvalue()


def test_profile_selection(root):
    out = io.StringIO()
    assert main(["--nanecisto"], root=root, input_fn=lambda _: "2", output=out) == 0
    run = _only_run(root)
    assert run.state.output_profile_name == "smernice"
    assert "Nabídka, nebo směrnice?" in out.getvalue()
    assert (run.directory / "FINALNI_smernice.docx").exists()


def test_single_profile_needs_no_selection(root):
    (root / "profiles" / "policy.yaml").unlink()
    assert main(["--nanecisto"], root=root, input_fn=_forbid_input, output=io.StringIO()) == 0
    assert _only_run(root).state.output_profile_name == "nabidka"


def test_eof_during_selection_returns_2(root):
    def eof(_):
        raise EOFError

    out = io.StringIO()
    assert main(["--nanecisto"], root=root, input_fn=eof, output=out) == 2
    assert not (root / "output").exists()


def test_configuration_error_returns_2(root):
    (root / "settings.yaml").write_text("loop: [\n", encoding="utf-8")
    out = io.StringIO()
    assert main(["--nanecisto"], root=root, input_fn=lambda _: "1", output=out) == 2
    assert "settings.yaml" in out.getvalue()
    assert not (root / "output").exists()


def test_empty_request_returns_2(root):
    (root / "input" / "poptavka.md").write_text("  \n", encoding="utf-8")
    out = io.StringIO()
    assert main(["--nanecisto"], root=root, input_fn=lambda _: "1", output=out) == 2
    assert "neobsahuje žádný text" in out.getvalue()


# ---------------------------------------------------------------- resume

def _factory_fails_evaluation_1(configuration, dry_run):
    writer, _ = demo_models()
    return writer, FakeModel({'evaluation_1': [ModelError('network', "OpenAI")]}, name="gpt-falesny")


def test_resume_without_value_finds_latest(root, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-klic")
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    out = io.StringIO()
    assert main([], root=root, input_fn=lambda _: "1", output=out,
                model_factory=_factory_fails_evaluation_1) == 1
    assert "resume.bat" in out.getvalue()
    assert _only_run(root).state.status == 'interrupted'

    models = []

    def model_factory(configuration, dry_run):
        models.append(demo_models())
        return models[-1]

    assert main(['--resume'], root=root, input_fn=_forbid_input, output=io.StringIO(),
                model_factory=model_factory) == 0
    run = _only_run(root)
    assert run.state.status == 'completed'
    writer = models[0][0]
    assert 'requirements' not in [step for step, _, _ in writer.calls]


def test_resume_explicit_directory(root):
    assert main(["--nanecisto"], root=root, input_fn=lambda _: "1", output=io.StringIO(),
                model_factory=_factory_fails_evaluation_1) == 1
    directory = next((root / "output").iterdir())
    assert main(["--nanecisto", '--resume', directory.name], root=root, input_fn=_forbid_input,
                output=io.StringIO()) == 0
    assert Run.open(directory).state.status == 'completed'


def test_resume_no_interrupted_run(root):
    out = io.StringIO()
    assert main(["--nanecisto", '--resume'], root=root, input_fn=_forbid_input, output=out) == 2
    assert "output" in out.getvalue()


def test_resume_completed_run_returns_2(root):
    assert main(["--nanecisto"], root=root, input_fn=lambda _: "1", output=io.StringIO()) == 0
    directory = next((root / "output").iterdir())
    out = io.StringIO()
    assert main(["--nanecisto", '--resume', str(directory)], root=root, input_fn=_forbid_input,
                output=out) == 2
    assert "dokončený" in out.getvalue()


# ---------------------------------------------------------------- demo versus live run

def _interrupted_live(root: Path, monkeypatch) -> Path:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-klic")
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    assert main([], root=root, input_fn=lambda _: "1", output=io.StringIO(),
                model_factory=_factory_fails_evaluation_1) == 1
    return max((root / "output").iterdir(), key=lambda p: Run.open(p).state.created_at)


def _interrupted_demo(root: Path) -> Path:
    assert main(["--nanecisto"], root=root, input_fn=lambda _: "1", output=io.StringIO(),
                model_factory=_factory_fails_evaluation_1) == 1
    return max((root / "output").iterdir(), key=lambda p: Run.open(p).state.created_at)


def test_run_mode_is_saved(root, monkeypatch):
    assert Run.open(_interrupted_demo(root)).state.dry_run is True
    assert Run.open(_interrupted_live(root, monkeypatch)).state.dry_run is False


def test_live_resume_of_demo_returns_2(root, monkeypatch):
    directory = _interrupted_demo(root)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-klic")
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    out = io.StringIO()
    assert main(['--resume', directory.name], root=root, input_fn=_forbid_input, output=out,
                model_factory=lambda configuration, n: demo_models()) == 2
    assert "ukázkový" in out.getvalue() and "--dry-run" in out.getvalue()
    assert Run.open(directory).state.status == 'interrupted'


def test_demo_resume_of_live_run_returns_2(root, monkeypatch):
    directory = _interrupted_live(root, monkeypatch)
    out = io.StringIO()
    assert main(["--nanecisto", '--resume', str(directory)], root=root, input_fn=_forbid_input,
                output=out) == 2
    assert "ostrý" in out.getvalue()
    assert Run.open(directory).state.status == 'interrupted'


def test_resume_latest_skips_other_mode(root, monkeypatch):
    live = _interrupted_live(root, monkeypatch)
    demo = _interrupted_demo(root)   # newer
    assert main(['--resume'], root=root, input_fn=_forbid_input, output=io.StringIO(),
                model_factory=lambda configuration, n: demo_models()) == 0
    assert Run.open(live).state.status == 'completed'
    assert Run.open(demo).state.status == 'interrupted'
    assert main(["--nanecisto", '--resume'], root=root, input_fn=_forbid_input,
                output=io.StringIO()) == 0
    assert Run.open(demo).state.status == 'completed'


def test_resume_only_other_mode_returns_2(root):
    _interrupted_demo(root)
    os.environ["ANTHROPIC_API_KEY"] = os.environ["OPENAI_API_KEY"] = "test-klic"
    out = io.StringIO()
    try:
        assert main(['--resume'], root=root, input_fn=_forbid_input, output=out,
                    model_factory=lambda configuration, n: demo_models()) == 2
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)
    assert "přerušený" in out.getvalue() and "--dry-run" in out.getvalue()


def test_resume_uses_current_model_settings(root, monkeypatch):
    directory = _interrupted_live(root, monkeypatch)
    settings = root / "settings.yaml"
    settings.write_text(settings.read_text(encoding="utf-8")
                         .replace("max_output_tokens: 64000", "max_output_tokens: 99000"), encoding="utf-8")
    configurations = []

    def model_factory(configuration, n):
        configurations.append(configuration)
        return demo_models()

    assert main(['--resume'], root=root, input_fn=_forbid_input, output=io.StringIO(),
                model_factory=model_factory) == 0
    assert configurations[0].settings.models.gpt.max_output_tokens == 99000
    assert "prices_usd_per_million" in (directory / "data" / "beh.log").read_text(encoding="utf-8")

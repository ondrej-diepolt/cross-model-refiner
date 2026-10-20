"""Run lifecycle: creation, resume, completion, and error recovery (design sections 8 and 9)."""
from __future__ import annotations

import logging
import shutil
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from refiner.artifacts import (
    CONFIGURATION_DIRECTORY, LOG_FILE, MATERIALS_FILE, STATE_FILE, PROMPT_SNAPSHOT_NAMES,
    canonical_profile_id,
)
from refiner.run import Run
from refiner.configuration import (
    ConfigurationError,
    Configuration,
    criteria_path_for_request,
    load_configuration,
    load_settings,
)
from refiner.steps import Sources
from refiner.models.errors import ModelError
from refiner.models.interface import Model
from refiner.comparison import compare
from refiner.loop import run_loop
from refiner.input import InputError, read_as_markdown, read_materials, resolve_materials_directory
from refiner.output.docx import export_docx
from refiner.output.overview import create_overview

_log = logging.getLogger(__name__)

CTRL_C_MESSAGE = "Přerušeno uživatelem (Ctrl+C)."
UNEXPECTED_ERROR_MESSAGE = "Neočekávaná chyba programu – podrobnosti v data/beh.log."
RESUME_MESSAGE = "Pokračovat: resume.bat"
COMPARE_AGAIN_MESSAGE = "Stav běhu se nezměnil; porovnání zopakujete spuštěním compare.bat."


# ---------------------------------------------------------------- start and resume

def _repository_models(
    run: Run,
    configuration: Configuration,
    root: Path,
    report: Callable[[str], None] | None,
) -> Configuration:
    """Refresh models and token prices from repository settings.yaml.

    Keep saved loop settings, weights, profile, criteria, and prompts for reproducible
    scoring. Invalid or missing repository settings use the snapshot with a warning."""
    file = root / "settings.yaml"
    with _run_log(run):
        try:
            current = load_settings(file)
        except ConfigurationError as e:
            message = (f"Varování: nastavení modelů z {file} nelze použít ({e}); běh pokračuje "
                      f"s nastavením modelů z kopie ve složce běhu ({CONFIGURATION_DIRECTORY}/nastaveni.yaml).")
            _log.warning("Repository model settings could not be loaded from %s: %s; using saved settings.", file, e)
            if report is not None:
                report(message)
            return configuration
        _log.info("Settings: models and prices_usd_per_million from current %s; loop, weights, "
                  "profile and prompts from the run snapshot (%s).", file, CONFIGURATION_DIRECTORY)
    settings = configuration.settings.model_copy(update={
        "models": current.models, "prices_usd_per_million": current.prices_usd_per_million})
    return replace(configuration, settings=settings)


def _load_sources(run: Run, root: Path | None = None,
                  report: Callable[[str], None] | None = None) -> Sources:
    """Read configuration, prompts, request, and materials from the run snapshot.

    When root is supplied, refresh only model settings and token prices."""
    configuration_directory = run.directory / CONFIGURATION_DIRECTORY
    criteria = configuration_directory / "kriteria.yaml"
    configuration = load_configuration(
        configuration_directory / "nastaveni.yaml",
        configuration_directory / "profil.yaml",
        criteria if criteria.exists() else None,
    )
    # The snapshot is named profil.yaml; run state preserves its canonical ID and output token.
    configuration = replace(configuration, profile_id=run.state.profile_id,
                         output_profile_name=run.state.output_profile_name)
    if root is not None:
        configuration = _repository_models(run, configuration, root, report)
    materials = run.directory / MATERIALS_FILE
    return Sources(
        request=run.text('request'),
        materials=materials.read_text(encoding="utf-8") if materials.exists() else "",
        configuration=configuration,
        prompts=configuration_directory / "prompty",
    )


def start_run(root: Path, input: Path, profile_id: str, now: datetime,
              dry_run: bool = False) -> tuple[Run, Sources]:
    """Create a run with configuration/prompt snapshots, request, materials, and dry-run mode."""
    settings = root / "settings.yaml"
    profile_id = canonical_profile_id(profile_id)
    profile_file = root / "profiles" / f"{profile_id}.yaml"
    criteria = criteria_path_for_request(input)
    # Validate configuration and input before creating a run directory.
    load_configuration(settings, profile_file, criteria)
    request = read_as_markdown(input)
    materials = read_materials(resolve_materials_directory(root))

    run = Run.new(root / "output", input.name, profile_id, now, dry_run=dry_run)
    configuration_directory = run.directory / CONFIGURATION_DIRECTORY
    configuration_directory.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(settings, configuration_directory / "nastaveni.yaml")
    shutil.copyfile(profile_file, configuration_directory / "profil.yaml")
    (configuration_directory / "prompty").mkdir()
    for name, snapshot_name in PROMPT_SNAPSHOT_NAMES.items():
        source = root / 'prompts' / f"{name}.md"
        if not source.is_file():
            source = root / 'prompts' / snapshot_name
        shutil.copyfile(source, configuration_directory / "prompty" / snapshot_name)
    if criteria is not None:
        shutil.copyfile(criteria, configuration_directory / "kriteria.yaml")
    run.write_fixed(MATERIALS_FILE, materials)
    run.write('request', "poptavka.md", request)
    return run, _load_sources(run)


def _open_run(directory: Path) -> Run:
    if not (directory / STATE_FILE).is_file():
        raise InputError(f"Složka {directory} není složka běhu (chybí {STATE_FILE}).")
    try:
        return Run.open(directory)
    except (OSError, ValidationError) as e:
        raise InputError(f"Stav běhu ve složce {directory} nelze přečíst ({STATE_FILE}).") from e


def resume_run(
    directory: Path,
    root: Path | None = None,
    dry_run: bool | None = None,
    report: Callable[[str], None] | None = None,
) -> tuple[Run, Sources]:
    """Resume saved sources, optionally refreshing models/prices and requiring a matching mode."""
    run = _open_run(directory)
    if run.state.status == 'completed':
        raise InputError(f"Běh {directory.name} je už dokončený.")
    if not run.is_done('request'):
        raise InputError(f"Běh {directory.name} nelze obnovit: chybí uložená poptávka.")
    if dry_run is not None and run.state.dry_run != dry_run:
        if run.state.dry_run:
            raise InputError(f"Běh {directory.name} je ukázkový (--dry-run, falešné modely); "
                              'pokračovat v něm lze jen s volbou --dry-run.')
        raise InputError(f"Běh {directory.name} je ostrý běh se skutečnými modely; s volbou --dry-run "
                          'v něm pokračovat nelze. Spusťte resume.bat bez --dry-run.')
    return run, _load_sources(run, root, report)


def open_completed_run(
    directory: Path,
    root: Path | None = None,
    dry_run: bool | None = None,
    report: Callable[[str], None] | None = None,
) -> tuple[Run, Sources]:
    """Open a completed run for comparison, with the same snapshot and mode policy as resume."""
    run = _open_run(directory)
    if run.state.status != 'completed':
        raise InputError(f"Běh {directory.name} není dokončený; porovnat lze jen dokončený běh.")
    if dry_run is not None and run.state.dry_run != dry_run:
        if run.state.dry_run:
            raise InputError(f"Běh {directory.name} je ukázkový (--dry-run) s falešnými texty; "
                              "s referencí ho porovnat nelze.")
        raise InputError(f"Běh {directory.name} je ostrý běh; v ukázkovém režimu ho porovnat nelze.")
    return run, _load_sources(run, root, report)


def refresh_comparison_prompts(run: Run, prompts: Path) -> None:
    """Refresh only the three comparison prompts; preserve the saved evaluation and writer prompts."""
    destination = run.directory / CONFIGURATION_DIRECTORY / "prompty"
    for name, snapshot_name in PROMPT_SNAPSHOT_NAMES.items():
        if not name.startswith("comparison_"):
            continue
        source = prompts / f"{name}.md"
        if not source.is_file():
            source = prompts / snapshot_name
        if source.is_file():
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination / snapshot_name)


def find_latest_run(output: Path, statuses: set[str], dry_run: bool | None = None) -> Path | None:
    """Find the newest created_at among matching statuses, optionally filtering dry-run mode."""
    if not output.is_dir():
        return None
    found: list[tuple[datetime, str, Path]] = []
    for directory in output.iterdir():
        if not (directory / STATE_FILE).is_file():
            continue
        try:
            state = Run.open(directory).state
        except (OSError, ValidationError):
            continue
        if state.status in statuses and (dry_run is None or state.dry_run == dry_run):
            found.append((state.created_at, directory.name, directory))
    return max(found)[2] if found else None


# ---------------------------------------------------------------- completion

def _interrupt(
    run: Run,
    sources: Sources,
    writer: Model,
    evaluator: Model,
    report: Callable[[str], None],
    error: str,
) -> int:
    """Save interrupted state, attempt an overview, and report recovery guidance. Return 1."""
    try:
        # Flush usage for responses that failed later step validation.
        remaining = writer.take_usage() + evaluator.take_usage()
        if remaining:
            run.add_usage(remaining)
    except Exception:
        _log.exception("Could not save usage for the interrupted step.")
    run.finish('interrupted', error=error)
    try:
        create_overview(run, sources.configuration)
    except Exception:
        _log.exception("Could not create the interrupted run overview.")
    report(error)
    report(f"Rozpracovaný běh je uložen ve složce: {run.directory}")
    report(RESUME_MESSAGE)
    return 1


def _finish(
    run: Run,
    sources: Sources,
    writer: Model,
    evaluator: Model,
    report: Callable[[str], None],
    template: Path | None,
) -> int:
    try:
        result = run_loop(run, sources, writer, evaluator, report)
        final = run.text(f"draft_{result.final_version}")
        name = sources.configuration.output_profile_name
        run.write_fixed(f"FINALNI_{name}.md", final)
        try:
            export_docx(final, run.directory / f"FINALNI_{name}.docx", template)
        except Exception as e:
            _log.exception("DOCX export failed.")
            run.add_warning(
                f"Export do DOCX se nepodařil ({e}); finální text je v souboru FINALNI_{name}.md."
            )
        run.finish('completed', result.reason, final_version=result.final_version)
        overview = create_overview(run, sources.configuration)
        _log.info("Run completed (%s, final version %d).", result.reason, result.final_version)
        report(f"Hotovo. Přehled běhu: {overview}")
        return 0
    except ModelError as e:
        _log.exception("Model error: %s", e.message)
        if e.raw_response is not None:
            run.write_fixed(f"data/surova_odpoved_{datetime.now():%Y%m%d_%H%M%S}.txt", e.raw_response)
        return _interrupt(run, sources, writer, evaluator, report, e.message)
    except KeyboardInterrupt:
        _log.exception("Interrupted by user (Ctrl+C).")
        return _interrupt(run, sources, writer, evaluator, report, CTRL_C_MESSAGE)
    except Exception:
        _log.exception("Unexpected application error.")
        return _interrupt(run, sources, writer, evaluator, report, UNEXPECTED_ERROR_MESSAGE)


def finish_run(
    run: Run,
    sources: Sources,
    writer: Model,
    evaluator: Model,
    report: Callable[[str], None],
    template: Path | None,
) -> int:
    """Complete the loop and exports with a temporary file logger. Return 0 or recoverable 1."""
    with _run_log(run):
        _log.info("Run %s: start (status %s, completed steps: %s).",
                  run.directory.name, run.state.status, ", ".join(run.state.steps) or "none")
        return _finish(run, sources, writer, evaluator, report, template)


@contextmanager
def _run_log(run: Run) -> Iterator[None]:
    """Attach an append-only data/beh.log handler to the refiner logger for this operation."""
    logger = logging.getLogger("refiner")
    handler = logging.FileHandler(run.directory / LOG_FILE, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    previous_level = logger.level
    logger.addHandler(handler)
    if logger.getEffectiveLevel() > logging.INFO:
        logger.setLevel(logging.INFO)
    try:
        yield
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        handler.close()


# ---------------------------------------------------------------- reference comparison

def compare_run(
    run: Run,
    sources: Sources,
    reference_md: str,
    evaluator: Model,
    report: Callable[[str], None],
    reference_name: str | None = None,
) -> int:
    """Compare a completed run. Return 0, recoverable failure 1, or configuration error 2."""
    with _run_log(run):
        _log.info("Reference comparison %s: start.", reference_name or "(unnamed)")
        try:
            html = compare(run, sources, reference_md, evaluator, report, reference_name=reference_name)
        except ConfigurationError as e:
            report(str(e))
            return 2
        except ModelError as e:
            _log.exception("Model error during comparison: %s", e.message)
            if e.raw_response is not None:
                run.write_fixed(f"data/surova_odpoved_porovnani_{datetime.now():%Y%m%d_%H%M%S}.txt",
                                e.raw_response)
            # Completed runs retry comparison through compare.bat rather than resume.bat.
            report(e.message.replace("resume.bat", "compare.bat"))
            report(COMPARE_AGAIN_MESSAGE)
            return 1
        except KeyboardInterrupt:
            _log.exception("Interrupted by user (Ctrl+C).")
            report(CTRL_C_MESSAGE)
            report(COMPARE_AGAIN_MESSAGE)
            return 1
        except Exception:
            _log.exception("Unexpected comparison error.")
            report(UNEXPECTED_ERROR_MESSAGE)
            return 1
        _log.info("Comparison completed: %s", html)
        report(f"Hotovo. Porovnání s referencí: {html}")
        return 0

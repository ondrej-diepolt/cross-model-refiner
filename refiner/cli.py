"""Czech console interaction with English commands and retained Czech aliases.

Exit codes: 0 complete, 1 interrupted/retryable run or comparison, 2 input/configuration
error. Technical details go to data/beh.log; no console logging handler is installed."""
from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TextIO

from dotenv import load_dotenv

from refiner.application import (
    CTRL_C_MESSAGE,
    finish_run,
    find_latest_run,
    resume_run,
    refresh_comparison_prompts,
    open_completed_run,
    compare_run,
    start_run,
)
from refiner.configuration import (
    ConfigurationError,
    Configuration,
    criteria_path_for_request,
    available_profiles,
    load_configuration,
    load_settings,
)
from refiner.models.errors import ModelError, Service
from refiner.models.claude import ClaudeModel
from refiner.models.claude_cli import ClaudeCliModel
from refiner.models.codex_cli import CodexModel
from refiner.models.fakes import demo_models
from refiner.models.gpt import GptModel
from refiner.models.interface import Model
from refiner.comparison import read_reference, find_reference
from refiner.input import InputError, find_inputs, find_template, resolve_materials_directory

ROOT = Path(__file__).resolve().parent.parent

API_KEYS: tuple[tuple[str, Service], ...] = (("ANTHROPIC_API_KEY", "Anthropic"), ("OPENAI_API_KEY", "OpenAI"))
EVALUATOR_KEY: tuple[tuple[str, Service], ...] = (("OPENAI_API_KEY", "OpenAI"),)

ENV_EXAMPLE_MESSAGE = "Vzor najdete v souboru .env.example."
ENV_ENCODING_MESSAGE = "Soubor .env nelze přečíst – uložte ho v kódování UTF-8."
NO_INPUT_MESSAGE = "Ve složce input/ není žádná poptávka (DOCX, MD nebo TXT)."
NO_PROFILE_MESSAGE = "Ve složce profiles/ není žádný profil dokumentu (*.yaml)."
NO_INTERRUPTED_MESSAGE = ("Ve složce output/ není žádný přerušený ostrý běh, ve kterém by šlo pokračovat "
                          '(ukázkové běhy se dokončují s volbou --dry-run).')
NO_INTERRUPTED_DEMO_MESSAGE = ('Ve složce output/ není žádný přerušený ukázkový běh (--dry-run), '
                                    've kterém by šlo pokračovat (ostré běhy se dokončují bez --dry-run).')
NO_COMPLETED_MESSAGE = ("Ve složce output/ není žádný dokončený ostrý běh, který by šlo porovnat "
                          's referencí (ukázkové běhy --dry-run se neporovnávají).')
COMPARE_OPTIONS_MESSAGE = ('Příkaz compare nejde kombinovat s --dry-run ani --resume '
                         "(porovnání volá skutečný model GPT).")
END_OF_INPUT_MESSAGE = "Volba nebyla zadána (konec vstupu)."
DRY_RUN_MESSAGE = 'Ukázkový režim --dry-run: falešné modely, bez volání API a bez nákladů.'

INTERRUPTED_STATUSES = {'interrupted', 'running'}

ModelFactory = Callable[[Configuration, bool], tuple[Model, Model]]


# ---------------------------------------------------------------- console

def _prepare_stream(stream: TextIO) -> None:
    """Configure UTF-8 with replacement when the stream supports reconfigure."""
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        pass


class _Console:
    """Flush each console write and append completion text to an unfinished progress line."""

    def __init__(self, stream: TextIO | None):
        self._stream = stream
        self._unfinished = False

    def _write(self, text: str) -> None:
        if self._stream is None:
            return
        try:
            self._stream.write(text)
        except UnicodeEncodeError:
            encoding = getattr(self._stream, "encoding", None) or "ascii"
            self._stream.write(text.encode(encoding, errors="replace").decode(encoding))
        self._stream.flush()

    def __call__(self, text: str) -> None:
        if self._unfinished:
            self._unfinished = False
            if text.startswith("hotovo"):
                self._write(f" {text}\n")
                return
            self._write("\n")
        if text.endswith("…"):
            self._write(text)
            self._unfinished = True
        else:
            self._write(f"{text}\n")

    def finish(self) -> None:
        if self._unfinished:
            self._unfinished = False
            self._write("\n")


def _choose(console: _Console, input_fn: Callable[[str], str], question: str, options: list[str]) -> int:
    """Offer numbered options, retry invalid answers, and return the selected zero-based index."""
    console(question)
    for i, option in enumerate(options, start=1):
        console(f"  {i}) {option}")
    n = len(options)
    while True:
        answer = input_fn(f"Zadejte číslo 1–{n}: ").strip()
        if answer.isdigit() and 1 <= int(answer) <= n:
            return int(answer) - 1
        console(f"Neplatná volba „{answer}“. Zadejte číslo 1–{n}.")


# ---------------------------------------------------------------- run preparation

def _default_model_factory(configuration: Configuration, dry_run: bool) -> tuple[Model, Model]:
    if dry_run:
        return demo_models()
    models = configuration.settings.models
    if models.mode == "api":
        return ClaudeModel(models), GptModel(models)
    return ClaudeCliModel(models), CodexModel(models)


def _default_evaluator(configuration: Configuration) -> Model:
    models = configuration.settings.models
    return GptModel(models) if models.mode == "api" else CodexModel(models)


def _missing_keys(keys: tuple[tuple[str, Service], ...] = API_KEYS) -> list[Service]:
    return [service for variable, service in keys if not os.environ.get(variable, "").strip()]


def _profile_question(names: list[str]) -> str:
    """Build a Czech profile-selection question from profile names."""
    lowercase = [n[:1].lower() + n[1:] for n in names[1:]]
    parts = [names[0], *lowercase]
    return ", ".join(parts[:-1]) + ", nebo " + parts[-1] + "?"


def _choose_profile(root: Path, console: _Console, input_fn: Callable[[str], str]) -> str:
    profiles = available_profiles(root / "profiles")
    if not profiles:
        raise ConfigurationError(NO_PROFILE_MESSAGE)
    if len(profiles) == 1:
        return profiles[0]
    settings = root / "settings.yaml"
    names = [load_configuration(settings, root / "profiles" / f"{p}.yaml").profile.name for p in profiles]
    return profiles[_choose(console, input_fn, _profile_question(names), names)]


def _choose_input(root: Path, console: _Console, input_fn: Callable[[str], str]) -> Path:
    directory = root / "input"
    inputs = find_inputs(directory) if directory.is_dir() else []
    if not inputs:
        raise InputError(NO_INPUT_MESSAGE)
    if len(inputs) == 1:
        return inputs[0]
    return inputs[_choose(console, input_fn, "Kterou poptávku zpracovat?", [p.name for p in inputs])]


def _run_directory(root: Path, value: str, statuses: set[str], dry_run: bool) -> Path | None:
    """Resolve an explicit run directory or the latest matching run under output/."""
    if not value:
        return find_latest_run(root / "output", statuses, dry_run=dry_run)
    path = Path(value)
    if not path.is_absolute() and not path.exists() and (root / "output" / path).exists():
        path = root / "output" / path
    return path


def _reference_path(root: Path, value: str | None) -> Path:
    if value is None:
        return find_reference(root)
    path = Path(value)
    if not path.is_absolute() and not path.exists() and (root / path).exists():
        path = root / path
    return path


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m refiner",
        description="Cross-model refiner: Claude píše dokument, GPT ho hodnotí, Claude ho vylepšuje.",
    )
    p.add_argument("--dry-run", "--nanecisto", dest="dry_run", action="store_true",
                   help="ukázkový běh s falešnými modely, bez volání API a bez nákladů")
    p.add_argument("--resume", "--pokracovat", dest="resume", nargs="?", const="", default=None, metavar="SLOZKA",
                   help="dokončí přerušený běh (bez hodnoty poslední přerušený v output/)")
    subcommands = p.add_subparsers(dest="command", metavar="PRIKAZ")
    comparison_parser = subcommands.add_parser(
        "compare", aliases=["porovnat"], help="porovná dokončený běh s referenční nabídkou (volá jen hodnotitele GPT)",
        description="Porovná dokončený běh s ručně dotaženou referenční nabídkou (výstup porovnani.html).",
    )
    comparison_parser.set_defaults(command="compare")
    comparison_parser.add_argument("directory", nargs="?", default="", metavar="SLOZKA",
                          help="složka běhu (bez hodnoty poslední dokončený běh v output/)")
    comparison_parser.add_argument("--reference", default=None, metavar="SOUBOR",
                          help="referenční nabídka (výchozí: jediný soubor ve složce examples/)")
    return p


# ---------------------------------------------------------------- main entry point

def main(
    argv: list[str] | None = None,
    *,
    root: Path | None = None,
    input_fn: Callable[[str], str] = input,
    output: TextIO | None = None,
    model_factory: ModelFactory | None = None,
    open_overview: bool = False,
) -> int:
    """Start, resume, or compare a run; return exit code 0, 1, or 2."""
    stream = output if output is not None else sys.stdout
    if stream is not None:
        _prepare_stream(stream)
    console = _Console(stream)
    try:
        args = _parser().parse_args(argv)
    except SystemExit as e:   # Help or invalid arguments; argparse writes its own output.
        return e.code if isinstance(e.code, int) else 2
    # Comparison needs only the evaluator, so GPT/Codex does not require Claude.
    evaluator_factory = ((lambda configuration: model_factory(configuration, False)[1]) if model_factory is not None
                     else _default_evaluator)
    try:
        return _run(args, Path(root) if root is not None else ROOT, input_fn, console,
                      model_factory or _default_model_factory, evaluator_factory, open_overview)
    finally:
        console.finish()


def _run(
    args: argparse.Namespace,
    root: Path,
    input_fn: Callable[[str], str],
    console: _Console,
    model_factory: ModelFactory,
    evaluator_factory: Callable[[Configuration], Model],
    open_overview: bool,
) -> int:
    is_comparison = args.command == "compare"
    if is_comparison and (args.dry_run or args.resume is not None):
        console(COMPARE_OPTIONS_MESSAGE)
        return 2
    try:
        load_dotenv(root / ".env", encoding="utf-8")
    except (UnicodeDecodeError, OSError):   # .env saved in ANSI/cp1250 or UTF-16
        console(ENV_ENCODING_MESSAGE)
        return 2
    if args.dry_run:
        console(DRY_RUN_MESSAGE)
    else:
        # Mode and model settings always come from repository settings.yaml, including on resume.
        try:
            mode = load_settings(root / "settings.yaml").models.mode
        except ConfigurationError as e:
            console(str(e))
            return 2
        if mode == "api":
            missing = _missing_keys(EVALUATOR_KEY if is_comparison else API_KEYS)
            for service in missing:
                console(f"{ModelError('authentication', service).message} {ENV_EXAMPLE_MESSAGE}")
            if missing:
                return 2

    try:
        if is_comparison:
            # Comparison uses a live evaluator, so demo runs are skipped or rejected.
            directory = _run_directory(root, args.directory, {'completed'}, dry_run=False)
            if directory is None:
                console(NO_COMPLETED_MESSAGE)
                return 2
            run, sources = open_completed_run(directory, root=root, dry_run=False, report=console)
            refresh_comparison_prompts(run, root / 'prompts')
            reference = _reference_path(root, args.reference)
            reference_md = read_reference(reference)
            evaluator = evaluator_factory(sources.configuration)
            console(f"Porovnávám běh {run.directory} s referencí {reference.name}")
        elif args.resume is not None:
            directory = _run_directory(root, args.resume, INTERRUPTED_STATUSES, dry_run=args.dry_run)
            if directory is None:
                console(NO_INTERRUPTED_DEMO_MESSAGE if args.dry_run else NO_INTERRUPTED_MESSAGE)
                return 2
            # Current model settings/prices override the otherwise frozen snapshot.
            run, sources = resume_run(directory, root=root, dry_run=args.dry_run, report=console)
            console(f"Pokračuji v běhu: {run.directory}")
            writer, evaluator = model_factory(sources.configuration, args.dry_run)
        else:
            input = _choose_input(root, console, input_fn)
            profile_id = _choose_profile(root, console, input_fn)
            configuration = load_configuration(
                root / "settings.yaml",
                root / "profiles" / f"{profile_id}.yaml",
                criteria_path_for_request(input),
            )
            writer, evaluator = model_factory(configuration, args.dry_run)
            console(f"Poptávka: {input.name}, profil: {configuration.profile.name}")
            run, sources = start_run(root, input, profile_id, datetime.now(), dry_run=args.dry_run)
            console(f"Složka běhu: {run.directory}")
    except (ConfigurationError, InputError) as e:
        console(str(e))
        return 2
    except ModelError as e:
        console(e.message)
        return 2
    except EOFError:
        console(END_OF_INPUT_MESSAGE)
        return 2
    except KeyboardInterrupt:
        console(CTRL_C_MESSAGE)
        return 2
    except Exception as e:   # For example, damaged DOCX input or a file locked by another program.
        console(f"Běh se nepodařilo připravit: {type(e).__name__}: {e}")
        return 2

    if is_comparison:
        code = compare_run(run, sources, reference_md, evaluator, console, reference.name)
        html = "porovnani.html"
    else:
        template = find_template(resolve_materials_directory(root))
        code = finish_run(run, sources, writer, evaluator, console,
                      template)
        html = "prehled.html"
    if code == 0 and open_overview:
        try:
            webbrowser.open((run.directory / html).resolve().as_uri())
        except Exception:
            pass   # Opening the browser is optional; the report path has already been printed.
    return code

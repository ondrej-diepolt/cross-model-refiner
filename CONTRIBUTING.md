# Development

This project requires Python 3.10 or newer. Dependency versions in
`requirements.txt` are pinned; this naming refactor does not change them.
User setup and operation are documented in Czech in [README.md](README.md).

From the repository root on Windows, development setup is:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The launchers `run.bat`, `resume.bat`, and `compare.bat` call `_setup.bat`.
It creates the environment when necessary and compares `requirements.txt` with
`.venv/requirements.installed` before installing dependencies. Do not run setup
as part of an offline refactor verification.

## Entry points

```powershell
.venv\Scripts\python.exe -m refiner --help
.venv\Scripts\python.exe -m refiner --dry-run
.venv\Scripts\python.exe -m refiner --dry-run --resume [DIRECTORY]
.venv\Scripts\python.exe -m refiner compare [DIRECTORY] --reference FILE
```

Square brackets indicate optional arguments; omit the brackets when running a
command. The Czech aliases `--nanecisto`, `--pokracovat`, and `porovnat` remain
supported. All aliases use the same English parser destinations and application
APIs. Comparison cannot be combined with dry-run or resume and rejects demo runs.

Exit codes are 0 for completion, 1 for an interrupted run or failed comparison
that can be retried, and 2 for an input, configuration, or authentication setup
error. The console is Czech; technical log prose is English. Provider responses,
quoted input, and user-facing error details retain their original language.

Use injected models and temporary application roots in integration tests rather
than running the real repository inputs. `main` accepts `root`, `input_fn`,
`output`, `model_factory`, and `open_overview` for this purpose. Only the package
entry point enables automatic browser opening by default.

## Module responsibilities

| Module | Responsibility |
|---|---|
| `application.py` | Start, resume, finish, and compare runs; snapshot policy and error recovery |
| `cli.py`, `__main__.py` | Argument parsing, Czech selection/reporting, and process entry point |
| `configuration.py` | YAML validation, profiles, criteria, and configuration aliases |
| `input.py`, `facts.py` | Document/material reading and Czech fact/placeholder patterns |
| `data.py`, `run.py` | Domain schemas, versioned run state, numbered artifacts, atomic saves |
| `legacy.py`, `artifacts.py` | Explicit compatibility decoding and preserved output names |
| `steps.py`, `loop.py`, `scoring.py` | Prompt calls, validation/repair, resumable iteration, numeric scoring |
| `models/` | Provider adapters, fake responses, authentication errors, process isolation/cleanup |
| `comparison.py` | Five evaluator calls, reversed A/B comparisons, calibration and coverage |
| `output/`, `output/templates/` | Markdown/DOCX/diff exports and static HTML reports |

Source configuration lives in `settings.yaml` and `profiles/*.yaml`. Built-in
profile IDs are `proposal` and `policy`; their export tokens remain `nabidka` and
`smernice`. Source prompt filenames under `prompts/` use English names, with Czech
instructions and English placeholders/schema tokens.

## Language and compatibility boundaries

Maintained Python identifiers, source filenames, structured JSON keys/enums,
configuration keys, template contexts, and implementation comments use English.
User interaction, generated document prose, Czech language patterns, and output
filenames remain Czech. Rendering maps internal enums to Czech display labels.
Do not translate arbitrary strings or dictionaries recursively.

`artifacts.py` defines the generated-name boundary. In particular, every run keeps
`data/beh.json`, `data/beh.log`, `data/konfigurace/`, Czech prompt snapshot names
under `data/konfigurace/prompty/`, numbered files such as `04_hodnoceni_1.md`,
`prehled.html`, `porovnani.html`, and `porovnani_formular.md`. Final documents use
`FINALNI_<output_profile_name>.*`. Do not derive output filenames directly from
English step or profile IDs.

Run state uses schema version 2. A missing version is decoded as version 1 through
explicit field, enum, and step-ID mappings. Opening a run does not rewrite it;
later saves use canonical English state keys at the same Czech state path. Old
per-step JSON is validated independently of the enclosing state version, allowing
old and new payloads in one resumed run. Malformed and unsupported future state
versions are reported in Czech without overwriting the input. Historical custom
profile output tokens are preserved verbatim.

Validation-only aliases accept old Czech configuration and model fields, with
canonical English keys taking precedence. Dumps and JSON schemas expose English
keys. Schemas sent to providers keep all fields required, without added defaults
or numeric range constraints; step validation enforces scoring rules separately.

Legacy saved prompts retain their original bytes. Rendering supplies old
placeholder aliases and adds a Czech schema clarification when old structured
tokens are detected in the content. The filename alone does not determine whether
a template is legacy. Text-only draft and revision prompts receive no schema note.

Resume uses saved inputs, materials, scoring criteria, loop settings, and prompts.
Only model settings and token prices refresh from repository `settings.yaml`,
falling back to the snapshot with a warning if it cannot be loaded. Comparison
refreshes only its three prompts, retaining the saved evaluation prompt for
calibration. Repeated comparison appends usage and replaces reports while
preserving completion state and any filled questionnaire.

## Private input precedence

- An existing `materials/` directory takes precedence over legacy `podklady/`;
  their contents are never combined. Neither directory is renamed automatically.
- `template.docx` takes precedence over `sablona.docx` for DOCX export. Both names
  are excluded from material text sent to models.
- A request's `.criteria.yaml` sidecar takes precedence over `.kriteria.yaml`.

Private `.env`, input, materials, reference documents, and generated output are
ignored. The `/output/` ignore rule is anchored at the repository root so that
the maintained `refiner/output/` package can be tracked.

## Offline verification

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m compileall -q refiner
git diff --check
```

On a restricted Windows filesystem, use a fresh short temporary path and a
writable cache location, for example:

```powershell
$env:PYTEST_ADDOPTS = '--basetemp=.superpowers/verify-unique -o cache_dir=.superpowers/pytest-cache'
$env:PYTHONIOENCODING = 'utf-8'
.venv\Scripts\python.exe -m pytest -q
```

Choose a new basetemp each time: pytest removes an existing basetemp. Keep scratch
paths out of source control. `git diff --check` does not inspect untracked files,
so check new files directly as well.

`tests/conftest.py` blocks socket connections and real provider CLI execution,
and clears provider API keys for each test. Provider tests inject fake SDK clients
or process runners; loop/CLI tests use `FakeModel` and `tests/helpers.py`. DOCX
tests use the bundled local pandoc binary. Do not install packages, invoke real
providers, or read production `.env`, `input/`, `materials/`, or `output/` to make
tests pass.

`tests/fixtures/legacy/` contains immutable synthetic version-1 run trees.
`tests/fixtures/output_paths.json` freezes generated output names. Never regenerate
or translate those payloads from new models. Compatibility tests copy them into
temporary directories before saving, resuming, or comparing. Relevant suites are
`test_legacy.py`, `test_output_contract.py`, `test_application.py`, `test_cli.py`,
`test_comparison.py`, and `test_overview.py`.

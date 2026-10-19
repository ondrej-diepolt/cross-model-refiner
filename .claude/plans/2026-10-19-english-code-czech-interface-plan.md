# English Code, Czech Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Choose the execution method with the user before implementation; do not dispatch implementation agents merely because this header lists them.

**Goal:** Translate maintained code and source filenames into English while preserving Czech interaction, document contents, and every generated output naming convention.

**Architecture:** Keep the existing Python application and module responsibilities. Translate leaf modules first, configuration next, then the connected data/prompt/run contracts together; isolate legacy decoding and preserved output paths at their boundaries. All stages must leave the offline suite runnable, and old saved runs must remain readable throughout.

**Tech Stack:** Python >=3.10, Pydantic 2.14.1, PyYAML 6.0.3, Jinja2 3.1.6, pytest 9.1.1, existing Anthropic/OpenAI SDKs, python-dotenv, pypandoc-binary, Windows batch launchers. No dependency changes.

**Spec:** [Approved design](2026-10-19-english-code-czech-interface-design.md). Read it before this plan, especially the corrected generated-output boundary.

## Global Constraints

- "The user explicitly requested English code, including filenames and class names, while retaining Czech output, messages, and interactive choices."
- "This applies to new and existing runs alike": generated output filenames retain their current Czech names.
- "Preserve step numbering and all remaining naming patterns."
- "New snapshots still contain the exact configuration and prompt content actually used, with English technical keys/placeholders."
- "Keep `data/beh.json` as the state filename for every run"; never introduce `data/run.json`.
- "Keep frozen scoring criteria and prompt semantics on resume." Current model settings/prices come from repository `settings.yaml`; comparison refreshes only comparison prompts.
- "Do not change models, prices, retries, authentication, network isolation, process cleanup, extraction rules, scoring, revision limits, or document structure."
- "Do not read or edit `.env` as part of translation."
- "Do not translate historical design/plan files, user documents, existing generated output, third-party code, virtual environments, caches, provider identifiers, or secrets."
- "Work in the current checkout. Do not commit, push, merge, rebase, create a PR, or create a worktree. Preserve unrelated changes."
- "Designs and plans belong under `.claude/plans/`. No task in this design creates or rewrites a skill."
- Retain Python >=3.10 and the exact dependency pins in `requirements.txt`; use `.venv\Scripts\python.exe` for verification.
- All test model calls are fake or mocked. Preserve the autouse network/real-CLI guards in `tests/conftest.py` as their patch targets move.
- A checkpoint below means stop, report the belonging files, and suggest the supplied commit message. The user performs Git operations. Never turn the checkpoint into a Git command.

## Review Focus

1. A resumed run whose evaluation file exists but whose score was not saved must recompute that score without paying for that evaluation again (Task 4).
2. An old saved prompt and a newly refreshed comparison prompt can coexist under Czech snapshot filenames; both must render with the English schema without changing business instructions (Tasks 4 and 5).
3. A custom profile must keep its historical final-output token even after built-in `proposal`/`policy` identifiers become English (Tasks 3 and 6).
4. If both old and new material directories or criteria sidecars exist, the documented English-path precedence must prevent duplicate or unintended input (Task 3).
5. Invalid YAML must still report the actual source key and line in Czech, for either a saved Czech-key configuration or a new English-key configuration (Task 3).

Each item has a named test below; this list records risks found beyond the existing happy-path tests.

---

## File structure and responsibility

This is one refactor with shared contracts, not independent subsystem projects. Execute tasks in order; update a renamed public API's callers in the same task. Do not leave compatibility import shims or Czech Python aliases behind. A consumer may retain its old module name until its own task, but must call the current API correctly.

| Current file/directory | Destination | Owner / responsibility |
|---|---|---|
| `refiner/fakta.py` | `refiner/facts.py` | Task 2: Czech fact and placeholder detection |
| `refiner/vstup.py` | `refiner/input.py` | Task 2: input reading; Task 3: material path precedence |
| `refiner/modely/` | `refiner/models/` | Task 2: provider, subprocess, error, and fake-model contracts |
| `modely/rozhrani.py`, `podproces.py`, `chyby.py`, `falesne.py` | `models/interface.py`, `subprocess.py`, `errors.py`, `fakes.py` | Rename within the package; other provider basenames remain English |
| `refiner/konfigurace.py` | `refiner/configuration.py` | Task 3: YAML models, validation, profiles, sidecars |
| New `refiner/artifacts.py` | same | Task 3: fixed Czech output paths, profile output tokens, source-to-snapshot filename map |
| New `refiner/legacy.py` | same | Task 4: old state identifiers and legacy prompt token/variable adaptation only |
| `refiner/data.py` | same | Task 4: English domain fields; old-field validation aliases |
| `refiner/beh.py`, `skore.py` | `refiner/run.py`, `scoring.py` | Task 4: state persistence and unchanged scoring |
| `refiner/kroky.py`, `smycka.py` | `refiner/steps.py`, `loop.py` | Task 4: prompt calls and resumable loop |
| `refiner/vystup/` | `refiner/output/` | Task 5: Czech Markdown, DOCX, diff and report rendering |
| `vystup/prehled.py`, `sablony/` | `output/overview.py`, `output/templates/` | English template context, preserved report destinations |
| `refiner/porovnani.py` | `refiner/comparison.py` | Task 5: reference comparison and its result schemas |
| `refiner/aplikace.py` | `refiner/application.py` | Task 6: lifecycle, current-versus-snapshot policy, error handling |
| `refiner/cli.py`, `__main__.py`, `__init__.py` | same | Task 6: English CLI/API names, Czech interaction |
| `nastaveni.yaml`, `profily/` | `settings.yaml`, `profiles/` | Task 3: English configuration structure, unchanged values |
| `profily/nabidka.yaml`, `smernice.yaml` | `profiles/proposal.yaml`, `policy.yaml` | Built-in IDs differ from Czech export tokens |
| `prompty/` | `prompts/` | Task 4: English source names/tokens, Czech instructions |
| `podklady.priklad/profil_firmy.md` | `materials.example/company_profile.md` | Task 3: Czech example contents |
| `spustit.bat`, `pokracovat.bat`, `porovnat.bat`, `_priprava.bat` | `run.bat`, `resume.bat`, `compare.bat`, `_setup.bat` | Task 6: Windows entry points |
| `README.md`, `.gitignore`; new `CONTRIBUTING.md` | same | Tasks 3/6: private-data exclusions and split user/developer guidance |
| `tests/pomocne.py` | `tests/helpers.py` | Task 4: English fake data builders |

Rename test modules with their owner: `test_fakta` -> `test_facts`, `test_vstup` -> `test_input`, `test_chyby` -> `test_errors`, `test_podproces` -> `test_subprocess`, `test_falesne` -> `test_fakes`, `test_konfigurace` -> `test_configuration`, `test_beh` -> `test_run`, `test_skore` -> `test_scoring`, `test_kroky` -> `test_steps`, `test_smycka` -> `test_loop`, `test_vystup` -> `test_output`, `test_prehled` -> `test_overview`, `test_porovnani` -> `test_comparison`, `test_aplikace` -> `test_application`. Already-English test basenames remain. Translate their test functions, fixtures, local names, and developer-only messages in the owning task.

## Shared naming contracts

These names lock interfaces that cross tasks; remaining private names follow the design vocabulary.

### Configuration contract (Task 3)

`Configuration` is the existing frozen dataclass translated to fields `settings: Settings`, `profile: Profile`, `profile_id: str`, `profile_criteria: list[ProfileCriterion]`, plus `output_profile_name: str`. Never infer the output token from the copied filename `profil.yaml`; restore it from run state when loading a snapshot.

| Existing fields | English fields / values |
|---|---|
| `nazev`, `popis`, `vaha` | `name`, `description`, `weight` |
| Profile `typ_dokumentu`, `pokyny_struktura`, `kriteria` | `document_type`, `structure_instructions`, `criteria` |
| Settings `modely`, `smycka`, `vahy_skupin`, `vychozi_profil`, `ceny_usd_za_milion` | `models`, `loop`, `group_weights`, `default_profile`, `prices_usd_per_million` |
| `rezim`, `predplatne`, `effort_extrakce`, `prikaz` | `mode`, `subscription`, `extraction_effort`, `command` |
| Mode `predplatne` | `subscription`; `api` stays `api` |
| `cilove_skore`, `max_revizi`, `min_nalezitost`, `max_navrhu` | `target_score`, `max_revisions`, `min_requirement_score`, `max_suggestions` |
| Price `vstup`, `vystup` | `input`, `output` |
| Sidecar `kriteria_navic`, `vahy` | `extra_criteria`, `weights` |

Translate settings class names directly (`NastaveniClaude` -> `ClaudeSettings`, `NastaveniGpt` -> `GptSettings`, etc.). Already-English API/provider fields such as `max_tokens_json`, `max_output_tokens`, `timeout_s`, and `effort` retain their names and values.

### Domain contract (Task 4)

| Current class | English class and fields |
|---|---|
| `Nalezitost` | `Requirement(id, text, citation)` |
| `VystupNalezitosti` | `RequirementsOutput(requirements)` |
| `Kriterium` | `Criterion(id, name, description, weight, group)` |
| `SkoreKriteria` | `CriterionScore(id, score, rationale, evidence)` |
| `VymyslenyFakt`, `TvrzeniKOvereni` | `FabricatedFact(citation, reason)`, `ClaimToVerify(citation, reason)` |
| `Navrh` | `RevisionSuggestion(id, criterion, location, problem, suggestion, priority)` |
| `Hodnoceni` | `Evaluation(criteria, fabricated_facts, claims_to_verify, suggestions, overall_comment)` |
| `Rozhodnuti` | `SuggestionDecision(suggestion_id, support, assumption, consequence, decision, rationale, implementation)` |
| `Posouzeni` | `SuggestionReview(decisions, summary)` |
| `VysledekSkore` | `ScoreResult(a, b, c, total, target_met, unmet_reasons)` |
| `Spotreba` | `TokenUsage(step, model, input_tokens, output_tokens, cache_read_tokens=0, cache_write_tokens=0, subscription=False)` |
| `ZaznamKroku` | `StepRecord(number, file, data=None)` |
| `StavBehu` | `RunState(schema_version=2, input, profile_id, output_profile_name, created_at, dry_run=False, ended_at=None, status="running", stop_reason=None, error=None, final_version=None, steps={}, scores={}, usage=[], warnings=[])` |
| `Zdroje` | `Sources(request, materials, configuration, prompts)` (frozen dataclass) |
| `VysledekBehu` | `RunResult(reason, final_version, scores)` (dataclass) |

Keep existing field types and required/default distinctions; the table's notation is a field inventory, not positional constructors. Add no defaults/range constraints to classes supplied to model structured-output APIs. Use independent default containers.

English enums: priorities `high/medium/low`; suggestion decisions `accepted/partial/rejected`; states `running/completed/interrupted`; stop reasons `target_reached/revision_limit/no_changes`. Map every existing Czech spelling explicitly at validation boundaries. IDs `N1`, `B1`, `U1`, `V1`, comparison labels `A/B`, and groups `A/B/C` stay unchanged.

Step IDs become `request`, `requirements`, `draft_N`, `evaluation_N`, `review_N`, `comparison_calibration`, `comparison_pair_1`, `comparison_pair_2`, `comparison_elements`, `comparison_coverage`. Filenames remain Czech and are never derived by simply interpolating these English IDs.

Validation aliases accept canonical English names first and old Czech names second; serialization and generated JSON schemas expose English only. Prefer `validation_alias=AliasChoices(...)` with the English name first, not serialization aliases. Before validators normalize old enum values. Do not recursively translate arbitrary dictionaries or string contents: criterion IDs, model names, citations, and user text must survive verbatim.

### Prompt source / snapshot contract (Tasks 3–5)

| English source under `prompts/` | Preserved name under `data/konfigurace/prompty/` |
|---|---|
| `requirements.md` | `nalezitosti.md` |
| `draft.md` | `navrh.md` |
| `evaluation.md` | `hodnoceni.md` |
| `review.md` | `posouzeni.md` |
| `revision.md` | `zapracovani.md` |
| `comparison_criteria.md` | `porovnani_kriteria.md` |
| `comparison_elements.md` | `porovnani_prvky.md` |
| `comparison_coverage.md` | `porovnani_pokryti.md` |

`PROMPT_SNAPSHOT_NAMES: dict[str, str]` in `artifacts.py` maps canonical prompt stems to saved basenames including `.md`. Config copies map repository `settings.yaml` -> `data/konfigurace/nastaveni.yaml`, selected profile -> `profil.yaml`, selected sidecar -> `kriteria.yaml`. Copy content without editing it.

Placeholders: `poptavka/podklady/typ_dokumentu/nalezitosti/pokyny_struktura/kriteria/max_navrhu/odmitnute` -> `request/materials/document_type/requirements/structure_instructions/criteria/max_suggestions/rejected_suggestions`. Keep Czech prose, headings, quotations, `[DOPLNIT: …]`, and existing Czech XML-like document markers unchanged: they delimit Czech language content and are already consumed by the fake models.

## Task 1: Freeze existing outputs and legacy-run fixtures

**Files:** Create `tests/test_output_contract.py`, `tests/fixtures/output_paths.json`, `tests/fixtures/legacy/interrupted/`, `tests/fixtures/legacy/completed/`. Modify `tests/conftest.py` only to expose `legacy_interrupted: Path` and `legacy_completed: Path` fixtures that copy those trees into `tmp_path`.

**Interfaces:** Consumes current `zahaj_beh`, `dokonci`, `Beh.otevri`, and fake scripts from `tests/pomocne.py`. Produces immutable, synthetic version-1 run fixtures with Czech JSON keys and snapshot prompt tokens, plus `test_existing_output_paths_and_czech_content` and `test_legacy_fixtures_match_current_reader`. Subsequent tasks translate these tests' API usage but never regenerate the frozen legacy payloads from new models.

- [x] **Step 1: Establish the baseline.** Run `.venv\Scripts\python.exe -m pytest -q`. Record the pass/fail/skip counts. Resolve or report pre-existing failures before treating them as regressions; do not install dependencies or call providers to make this planning stage pass.
- [x] **Step 2: Capture two synthetic old-format run trees.** Use the existing application in a temporary app root with fake writer/evaluator objects, `tests/pomocne.py`'s Czech request, and fixed time `datetime(2026, 10, 17, 9, 0)`. Capture an interrupted run after `navrh_2` with the evaluator raising before `hodnoceni_2`; capture a completed run with final version 1 and add a filled `porovnani_formular.md` containing `Odpověď: ano, 30 minut`. Include `data/beh.json`, all recorded step files/JSON, and the complete original configuration/prompt snapshots. Use `nanecisto=False` with injected fake models so the completed fixture is eligible for comparison. Exclude logs containing temporary absolute paths and generated DOCX binaries from committed fixtures; no private files, `.env`, or real `output/` contents.
- [x] **Step 3: Write the characterization tests and path manifest.** Record the numbered paths for the interrupted sequence and all static output/snapshot paths in `output_paths.json`; compare sets of relative paths, not absolute roots or timestamps. Assertions include:

```python
assert "06_navrh_v2_zmeny.html" in paths
assert "data/konfigurace/prompty/hodnoceni.md" in paths
assert "data/beh.json" in paths
assert "prehled.html" in paths
assert "Hotovo. Přehled běhu:" in console_text
assert "[DOPLNIT:" in final_text
assert "schema_version" not in legacy_state
assert legacy_state["stav"] == "prerusen"
```

The final-text/console assertions use a separate fresh fake completed run; the interrupted fixture asserts its saved draft/diff paths. Check each frozen fixture opens with today's reader. This is characterization of existing behavior, so these tests are expected to pass immediately, not manufacture a failing rename test.
- [x] **Step 4: Verify the fixture contract.** Run `.venv\Scripts\python.exe -m pytest tests/test_output_contract.py -q`, then the full suite. Expected: all pass, no network/real-model invocations.
- [x] **Step 5: User checkpoint.** Files: the new contract test, fixture trees/manifest, and `tests/conftest.py`. Suggested message: `test: freeze Czech output paths and legacy run fixtures`.

## Task 2: Translate leaf modules and provider APIs

**Files:** Rename source/test leaf and provider paths from the file-structure table. Modify all imports/call sites in remaining `refiner/` modules and `tests/` together, including `tests/conftest.py`. Keep configuration/domain classes owned by later tasks working; import them under English local aliases where necessary, then remove those aliases when their declarations are translated.

**Interfaces:**

- Produce `find_placeholders(md: str) -> list[str]`, `find_suspicious_facts(document: str, sources: str) -> list[SuspiciousFact]` in `facts.py`; `SuspiciousFact(kind, value)` uses `amount/company_id/email/phone/name/url` internally and renders through Czech labels later.
- Produce `find_inputs(directory: Path) -> list[Path]`, `read_as_markdown(path: Path) -> str`, `read_materials(directory: Path) -> str`, `slug(text: str, max_length: int = 60) -> str`, `InputError` in `input.py`.
- Translate `Model` protocol to `name: str`, `json(instructions: str, task: str, schema: type[T], *, step: str, effort: str | None = None) -> T`, `text(instructions: str, task: str, *, step: str) -> str`, `take_usage() -> list[TokenUsage]`. Until Task 4, `TokenUsage` is an English local import alias for existing `Spotreba`.
- Translate fake API to `FakeModel(responses: dict[str, list[Response]], name: str = "fake")`, `.calls: list[tuple[str, str, str]]`, and `demo_models() -> tuple[FakeModel, FakeModel]`. Keep existing response-queue semantics and demo scores `(7.5, 8.5, 9.0, 9.5)`.
- Translate subprocess contracts to `ProcessResult(returncode: int, stdout: str, stderr: str)` (frozen dataclass), `ProcessTimeout`, `clean_environment(source: Mapping[str, str] | None = None, extra: Mapping[str, str] | None = None) -> dict[str, str]`, `run_process(argv: list[str], stdin: str, env: dict[str, str], cwd: Path, timeout_s: float) -> ProcessResult`, `find_program(default: str, configured: str | None) -> Path | None`, `native_codex(path: Path) -> Path`, and context manager `temporary_directories() -> Iterator[tuple[Path, Path]]`. `Runner = Callable[[list[str], str, dict[str, str], Path, float], ProcessResult]`; injectable `run: Runner = run_process` is the test-guard patch target. Preserve Windows job/process cleanup behavior.
- Produce `ModelError(kind: ErrorKind, service: Service, detail: str = "", raw_response: str | None = None)` with `.message` in Czech and `.kind/.service/.detail/.raw_response`. Kinds become `authentication/credit/overloaded/network/timeout/invalid_output/truncated/refused/other/not_installed/not_authenticated/subscription_limit/model_unavailable` in the same order as the current Czech variants. Keep provider/service names unchanged.

- [ ] **Step 1: Rename the owned files and translate identifiers/comments/docstrings and callers as one mechanical refactor.** Keep Czech regex patterns, text fixtures, provider flags/environment names, and runtime message prose. Update fact-rendering dictionary keys alongside `SuspiciousFact.kind` while retaining their Czech labels. Replace error-message references to `nastaveni.yaml`/`pokracovat.bat` only when the actual assets are renamed in Tasks 3/6. Preserve existing tests' assertions while translating technical identifiers.
- [ ] **Step 2: Verify provider and language behavior.** Run `.venv\Scripts\python.exe -m pytest tests/test_facts.py tests/test_input.py tests/test_errors.py tests/test_subprocess.py tests/test_fakes.py tests/test_claude.py tests/test_gpt.py tests/test_claude_cli.py tests/test_codex_cli.py -q`. Expected: pass, including existing Czech name/currency detection, API-key scrubbing, subscription environment filtering, tool/network guards, long UTF-8 stdin and descendant-process termination tests.
- [ ] **Step 3: Verify integration.** Run the full offline suite. Expected: no broken imports or old `krok=`/`nazev=` calls into renamed provider APIs. This is an API-preserving mechanical rename; do not add tests that only assert a function has a new spelling.
- [ ] **Step 4: User checkpoint.** Files: leaf/provider sources/tests and their import/API consumers. Suggested message: `refactor: use English input fact and provider APIs`.

## Task 3: Translate configuration and preserve output-name boundaries

**Files:** Rename `refiner/konfigurace.py`, `tests/test_konfigurace.py`, root settings/profiles/example paths as mapped above. Create `refiner/artifacts.py`, `tests/test_artifacts.py`. Modify `refiner/input.py`, remaining application/CLI/scoring/step/report consumers, their tests, and `.gitignore`.

**Interfaces:**

- `load_settings(path: Path) -> Settings`, `load_configuration(settings: Path, profile: Path, criteria: Path | None = None) -> Configuration`, `criteria_path_for_request(request: Path) -> Path | None`, `available_profiles(directory: Path) -> list[str]` in `configuration.py`.
- `resolve_materials_directory(root: Path) -> Path` in `input.py`: existing `materials/` wins; otherwise existing `podklady/`; otherwise return `materials/`. Exclude both `template.docx` and `sablona.docx` from model text. Prefer `template.docx` within the selected directory, then `sablona.docx`, when exporting.
- `output_profile_name(profile_id: str) -> str` in `artifacts.py`: `proposal/nabidka` -> `nabidka`, `policy/smernice` -> `smernice`, other IDs unchanged. State/configuration store the explicit output token separately in Task 4.
- `STATE_FILE = "data/beh.json"`, `LOG_FILE = "data/beh.log"`, `CONFIGURATION_DIRECTORY = "data/konfigurace"`, `MATERIALS_FILE = "data/podklady.md"`, `OVERVIEW_FILE = "prehled.html"`, `COMPARISON_FILE = "porovnani.html"`, `COMPARISON_FORM = "porovnani_formular.md"`, and `PROMPT_SNAPSHOT_NAMES` as specified above. Adopt them in output writers without changing generated paths.

- [ ] **Step 1: Add failing boundary tests** in `test_artifacts.py`, `test_configuration.py`, and `test_input.py`:

```python
assert output_profile_name("proposal") == "nabidka"
assert output_profile_name("policy") == "smernice"
assert output_profile_name("custom_offer") == "custom_offer"
assert PROMPT_SNAPSHOT_NAMES["evaluation"] == "hodnoceni.md"
assert load_settings(english_settings).models.mode == "subscription"
assert load_settings(legacy_settings).models.mode == "subscription"
assert resolve_materials_directory(root) == root / "materials"
assert criteria_path_for_request(request) == request.with_suffix(".criteria.yaml")
```

Fixtures `english_settings` and `legacy_settings` are copies of equivalent translated/new and frozen/old YAML. The precedence tests create both alternative paths with distinct sentinel text and assert the returned/read content contains only the English-path sentinel. Also test missing directories and legacy-only sidecars/templates. For validation, parameterize invalid `weight` and `vaha` at line 6: assert the error contains the file basename, `řádek 6`, the actual key, and `musí být číslo`. Assert unknown keys remain forbidden and criterion-ID/weight rules remain unchanged.
- [ ] **Step 2: Run the targeted tests.** Command: `.venv\Scripts\python.exe -m pytest tests/test_artifacts.py tests/test_configuration.py tests/test_input.py -q`. Expected new tests fail on the missing APIs/English YAML support, not fixture syntax errors.
- [ ] **Step 3: Implement configuration/path contracts.** Translate the settings models/fields from the shared table, retaining validation-only old-key aliases and enum normalization; keep error locations tied to the original YAML nodes/keys, including manual weight/ID validation. Convert repository YAML keys and built-in IDs without changing numeric/model settings, Czech comments, criteria text, or structure instructions. Update root callers to `settings.yaml` and `profiles/`. When beginning a run, copy English source configuration to the existing Czech snapshot names. At this stage source prompts still have their old names: copy them unchanged; use the same fixed snapshot map when Task 4 renames source prompts. While old run code still stores `profil`, pass/store the output token there so this stage keeps final filenames unchanged.
- [ ] **Step 4: Implement input precedence.** Add the material-directory resolver and English sidecar-first lookup, update new-run and DOCX-template selection call sites, rename the example folder/file, and ignore both private `materials/` and legacy `podklady/`. Never move or rewrite private material directories. Update Czech error text only where an actual configuration path/key token changed.
- [ ] **Step 5: Verify.** Rerun targeted tests, `tests/test_output_contract.py`, then the full suite. Expected: all pass; `data/konfigurace/nastaveni.yaml` still exists in new runs, built-ins still export `FINALNI_nabidka.*`/`FINALNI_smernice.*`, and frozen old snapshots load. Old configuration checks without a mode still default to subscription.
- [ ] **Step 6: User checkpoint.** Files: configuration/assets, `artifacts.py`, input precedence, consumers/tests, `.gitignore`. Suggested message: `refactor: translate configuration while preserving Czech output names`.

## Task 4: Translate domain models, prompts, and resumable state together

**Files:** Rename `beh.py`, `skore.py`, `kroky.py`, `smycka.py` and their tests; modify `data.py`; create `legacy.py` and `tests/test_legacy.py`; rename `tests/pomocne.py` -> `tests/helpers.py`. Rename all eight source prompt files per the shared table. Modify every domain-field consumer in providers, application, CLI, comparison, renderers, and tests in the same task. Translate comparison schema field names here even though its module filename is renamed in Task 5.

**Interfaces:**

- `Run(directory: Path, state: RunState)`, `Run.new(output: Path, input_name: str, profile_id: str, now: datetime, dry_run: bool = False) -> Run`, `Run.open(directory: Path) -> Run`.
- Translate Run methods to `save() -> None`, `write(step: str, name: str, content: str, data: BaseModel | None = None) -> Path`, `write_for_step(step: str, name: str, content: str) -> Path`, `write_fixed(relative_path: str, content: str | bytes) -> Path`, `is_done(step: str) -> bool`, `text(step: str) -> str`, `data(step: str, model: type[T]) -> T`, `add_usage(items: list[TokenUsage]) -> None`, `add_warning(text: str) -> None`, `save_score(number: int, score: ScoreResult) -> None`, `finish(status: Literal["completed", "interrupted"], reason: str | None = None, error: str | None = None, final_version: int | None = None) -> None`.
- `normalize_run_state(payload: Mapping[str, Any]) -> dict[str, Any]`, `normalize_step_id(step: str) -> str`, `legacy_prompt_variables(variables: Mapping[str, str]) -> dict[str, str]`, `adapt_legacy_prompt(text: str, prompt_name: str) -> str` in `legacy.py`. No imports from run/application, no filesystem migration, and no arbitrary user-text translation. `adapt_legacy_prompt` preserves old prose and appends a Czech technical-field clarification for a recognized legacy structured-output template; it returns canonical/new templates unchanged.
- `render_prompt(directory: Path, name: str, **variables: str) -> str`, `extract_requirements(model: Model, sources: Sources) -> tuple[list[Requirement], list[str]]`, `write_draft(model: Model, sources: Sources, requirements: list[Requirement]) -> str` in `steps.py`.
- `evaluate(model: Model, sources: Sources, criteria: list[Criterion], document: str, rejected: list[tuple[RevisionSuggestion, SuggestionDecision]], step: str) -> tuple[Evaluation, list[str]]`, `review_suggestions(model: Model, sources: Sources, requirements: list[Requirement], document: str, evaluation: Evaluation, step: str) -> SuggestionReview`, `incorporate_suggestions(model: Model, sources: Sources, requirements: list[Requirement], document: str, evaluation: Evaluation, review: SuggestionReview, step: str) -> str`, `accepted_decisions(review: SuggestionReview) -> list[SuggestionDecision]` in `steps.py`.
- `calculate_score(evaluation: Evaluation, criteria: list[Criterion], settings: Settings) -> ScoreResult`, `select_final_version(scores: dict[int, ScoreResult]) -> int`, `format_score(value: float) -> str`; `run_loop(run: Run, sources: Sources, writer: Model, evaluator: Model, report: Callable[[str], None]) -> RunResult`.
- Helpers become `make_sources(repo_root: Path) -> Sources`, `make_run(tmp_path: Path, sources: Sources) -> Run`, `make_evaluation`, `make_review`, `scripted_models`, and `draft_text`. Preserve their existing optional arguments/types translated consistently and their Czech test content.

- [ ] **Step 1: Write failing compatibility tests** using the frozen run trees, not newly serialized English fixtures:

```python
run = Run.open(legacy_interrupted)
assert run.state.schema_version == 2
assert run.state.status == "interrupted"
assert run.state.profile_id == "proposal"
assert run.state.output_profile_name == "nabidka"
assert run.is_done("evaluation_1") and run.is_done("draft_2")
assert run.state.steps["draft_2"].file == "06_navrh_v2.md"
evaluation = run.data("evaluation_1", Evaluation)
assert evaluation.suggestions[0].priority in {"high", "medium", "low"}
run.save()
assert json.loads((run.directory / "data/beh.json").read_text(encoding="utf-8"))["schema_version"] == 2
assert not (run.directory / "data/run.json").exists()
assert "criteria" in Evaluation.model_json_schema()["properties"]
assert "kriteria" not in Evaluation.model_json_schema()["properties"]
```

Add `test_legacy_resume_does_not_repeat_completed_calls`: resume with fake responses for remaining steps only and assert the writer/evaluator call lists omit `requirements`, `draft_1`, `evaluation_1`, `review_1`, and `draft_2`. Add `test_missing_saved_score_reuses_evaluation`: remove old `skore["1"]` before opening the interrupted fixture; resume, assert score 1 is recalculated and no `evaluation_1` call occurs. Reopen after another save/interruption and read the still-Czech per-step JSON: upgrading the state version must not prevent mixed old/new step payloads from loading. Add malformed-state and unknown-future-version tests expecting a Czech user error via the lifecycle boundary, not an automatic overwrite.
- [ ] **Step 2: Add prompt/schema tests.** `test_legacy_prompt_uses_canonical_schema_tokens` renders frozen `hodnoceni.md` with English variables: assert no `${` remains, the appended clarification contains English field/priority names, and original Czech instructions about score range `1–10`, increments `0,5`, and `[DOPLNIT: …]` remain. In `test_legacy_review_disambiguates_decisions_and_decision`, assert the clarification distinguishes old root `rozhodnuti` -> `decisions` from item `rozhodnuti` -> `decision`, preserving the original business prose. A newly saved Czech-named template with English placeholders must not receive a legacy clarification merely because its filename is Czech. Parameterize all eight templates, all structured-output schema families, and both source/snapshot filename resolution. Assert legacy aliases/enum spellings validate but dumps and schemas contain English keys/tokens. Keep model schema required/default restrictions unchanged. Run `.venv\Scripts\python.exe -m pytest tests/test_legacy.py -q`; expected failures on missing English contracts.
- [ ] **Step 3: Translate data/run/scoring/loop contracts and consumers as one atomic stage.** Implement English fields with validation-only legacy aliases. Normalize nested state, step IDs and usage step IDs using explicit typed mappings; detect absent version as v1 and accept v2; retain atomic `.tmp` + `os.replace` persistence. Add `output_profile_name` to state, preserving old custom profile tokens. Keep loading old per-step JSON independent of the enclosing run version. Reject unknown future versions through the existing Czech input-error path. Update fakes, usage accounting, comparison schemas and all renderers to English domain fields. Preserve raw-response/canonical schema validation and the existing single repair attempt; translate provider SDK calls to the renamed schema classes without changing provider capabilities. Keep scoring/tie-breaking and existing numeric assertions unchanged, including demo totals `[7.9, 8.7, 9.2, 9.6]`.
- [ ] **Step 4: Translate maintained prompts and adapt old snapshots at rendering time.** Rename source files, update `${...}`, backticked schema keys and enum tokens to English, retain Czech business prose and markers. Resolve canonical names against an English source filename first and its mapped Czech snapshot filename second. Recognize legacy template content by known Czech placeholders/schema references, not the saved filename. Supply old placeholder aliases and append a Czech note that the supplied schema's English keys/enums are authoritative, listing the corresponding old/new technical paths for that template. Preserve original prose instead of replacing ambiguous words such as `rozhodnuti` globally; root and item paths have different translations. Text-only draft/revision templates need placeholder aliases but no schema note. Never modify old saved prompt files. Validation aliases accept an old response if a legacy prompt still produces Czech technical fields. Unknown template variables still fail before model calls with Czech explanations.
- [ ] **Step 5: Preserve snapshot and model policies.** Update run creation to copy each renamed prompt to its mapped Czech output filename without changing content. Do not derive snapshots from English directory names. Resume still uses saved evaluation/draft/review prompts; comparison refreshes only the three comparison prompt files. Current model settings/prices keep their existing override policy. No re-running completed steps or rewriting historical step files on load.
- [ ] **Step 6: Verify.** Run `.venv\Scripts\python.exe -m pytest tests/test_legacy.py tests/test_run.py tests/test_scoring.py tests/test_steps.py tests/test_loop.py tests/test_output_contract.py -q`, then the full suite. Expected: all pass; legacy, mixed, and new payloads work with identical filenames and Czech generated text. No old `Spotreba` import aliases remain.
- [ ] **Step 7: User checkpoint.** Files: core domain/run/steps/loop, `legacy.py`, renamed prompts/helper/tests, all changed domain consumers. Suggested message: `refactor: translate domain contracts and retain legacy run compatibility`.

## Task 5: Translate reports and reference comparison

**Files:** Rename `refiner/vystup/` -> `refiner/output/`, `prehled.py` -> `overview.py`, `sablony/` -> `templates/`, `prehled.html.j2` -> `overview.html.j2`, `porovnani.html.j2` -> `comparison.html.j2`; rename `refiner/porovnani.py` -> `refiner/comparison.py` and owned test modules. Modify their callers, `artifacts.py` and fake comparison helpers as needed.

**Interfaces:**

- `create_overview(run: Run, configuration: Configuration) -> Path`, `export_docx(md: str, destination: Path, template: Path | None) -> None`; `requirements_markdown(requirements: list[Requirement], warnings: list[str]) -> str`, `evaluation_markdown(number: int, evaluation: Evaluation, score: ScoreResult, criteria: list[Criterion]) -> str`, `review_markdown(number: int, evaluation: Evaluation, review: SuggestionReview) -> str`; `diff_html(old: str, new: str, old_label: str, new_label: str) -> str`.
- Comparison schemas (English fields established in Task 4) become `CriterionComparison(id, better, rationale)`, `PairComparison(criteria)`, `ReferenceElement(id, description)`, `ReferenceElements(elements)`, `ElementCoverage(id, status, comment)`, `Coverage(items)`, `ComparisonResult(reference_score, generated_score, comparison, rationales, elements, coverage)`.
- `better` uses `A/B/tie`; coverage uses `present/partial/missing`; verdict uses `generated/reference/tie`. Legacy spellings remain validation-only input aliases. Czech output labels are explicit mappings.
- `compare(run: Run, sources: Sources, reference_md: str, evaluator: Model, report: Callable[[str], None], *, reference_name: str | None = None) -> Path`, `find_reference(root: Path) -> Path`, `read_reference(path: Path) -> str`, `combine_comparisons(first: PairComparison, second: PairComparison) -> dict[str, Verdict]`.

- [ ] **Step 1: Add regression tests** in `test_overview.py` and `test_comparison.py` for untranslated enum leakage and legacy form preservation:

```python
form = legacy_completed / "porovnani_formular.md"
before = form.read_bytes()
path = compare(run, sources, reference_md, evaluator, lambda _: None)
assert path.name == "porovnani.html"
assert form.read_bytes() == before
assert "Odpověď: ano, 30 minut" in form.read_text(encoding="utf-8")
assert run.state.status == "completed"
assert len(evaluator.calls) == 5
assert (run.directory / "data/porovnani.json").exists()
```

Construct `run`/`sources` from the frozen completed fixture using the already-working lifecycle loader; provide five mocked comparison responses. Assert the fresh report renders Czech priority/coverage/status/verdict labels, final links point to `FINALNI_nabidka.md`, and no `comparison.html`/`overview.html` output file is created. Add a custom-profile case asserting `FINALNI_custom_offer.md` is linked; built-in policy still links `FINALNI_smernice.md`.
- [ ] **Step 2: Run the targeted regressions before changing rendering.** Command: `.venv\Scripts\python.exe -m pytest tests/test_overview.py tests/test_comparison.py -q` after mechanical file/import renames. If a required label mapping is missing, first demonstrate its failing assertion before fixing it. Otherwise these characterize behavior already preserved in Task 4 and should pass; a pure filename rename must not manufacture a red test.
- [ ] **Step 3: Translate owned implementation and templates.** Use English locals, helper names, context keys, CSS/HTML implementation identifiers and technical logs. Translate source template names only; render to the Czech destinations from `artifacts.py`. Map English enums to the exact prior Czech labels, including priority strings that previously reached Markdown directly. Keep HTML escaping, decimal commas, score colors, cache-price calculations, subscription flags, comparison call order and A/B reversal unchanged.
- [ ] **Step 4: Verify mixed prompt sources and repeated comparison.** Add `test_comparison_refresh_preserves_saved_evaluation`: refresh the three comparison templates from English sources into Czech snapshot filenames; assert the saved evaluation prompt bytes are unchanged, all five calls render successfully, and stale old comparison tokens do not cause schema errors. Rerun `.venv\Scripts\python.exe -m pytest tests/test_output.py tests/test_overview.py tests/test_comparison.py tests/test_output_contract.py tests/test_legacy.py -q`, then the full suite. Expected: pass; comparison appends usage without changing completion/final-version state or questionnaire answers.
- [ ] **Step 5: User checkpoint.** Files: renamed renderer/comparison sources/templates/tests, label maps and consumers. Suggested message: `refactor: translate rendering code while retaining Czech reports`.

## Task 6: Translate application lifecycle, CLI, launchers, and documentation

**Files:** Rename `refiner/aplikace.py` -> `refiner/application.py`, `tests/test_aplikace.py` -> `tests/test_application.py`, and the four batch files. Modify `cli.py`, package entry points, `tests/test_cli.py`, lifecycle/comparison consumers, `README.md`; create `CONTRIBUTING.md`. Translate any remaining developer comments/test names in already-English files. Inspect `.env.example` guidance by audience; preserve Czech user setup instructions and existing variable names.

**Interfaces:**

- `start_run(root: Path, input: Path, profile_id: str, now: datetime, dry_run: bool = False) -> tuple[Run, Sources]`, `resume_run(directory: Path, root: Path | None = None, dry_run: bool | None = None, report: Callable[[str], None] | None = None) -> tuple[Run, Sources]`, `open_completed_run(directory: Path, root: Path | None = None, dry_run: bool | None = None, report: Callable[[str], None] | None = None) -> tuple[Run, Sources]`.
- `refresh_comparison_prompts(run: Run, prompts: Path) -> None`, `find_latest_run(output: Path, statuses: set[str], dry_run: bool | None = None) -> Path | None`.
- `finish_run(run: Run, sources: Sources, writer: Model, evaluator: Model, report: Callable[[str], None], template: Path | None) -> int`, `compare_run(run: Run, sources: Sources, reference_md: str, evaluator: Model, report: Callable[[str], None], reference_name: str | None = None) -> int`.
- `main(argv: list[str] | None = None, *, root: Path | None = None, input_fn: Callable[[str], str] = input, output: TextIO | None = None, model_factory: ModelFactory | None = None, open_overview: bool = False) -> int`; `ModelFactory = Callable[[Configuration, bool], tuple[Model, Model]]`.
- Canonical CLI `--dry-run`, `--resume [SLOZKA]`, `compare [SLOZKA] --reference SOUBOR`. Keep `--nanecisto`, `--pokracovat`, `porovnat` as parser aliases targeting the same English namespace attributes. Retain mutually exclusive behavior and return codes 0/1/2. Metavariables and help explanations remain Czech.

- [ ] **Step 1: Add failing CLI compatibility tests.** Parameterize `--dry-run/--nanecisto`, `--resume/--pokracovat`, and `compare/porovnat` to assert the same injected model calls, selection behavior, and exit codes. Check malformed option combinations return 2 with Czech guidance and comparison rejects demo runs. New English options fail before parser support is added.

```python
assert main(["--dry-run"], root=app_root, input_fn=lambda _: "1", output=out) == 0
assert "Hotovo. Přehled běhu:" in out.getvalue()
assert (only_run / "prehled.html").exists()
assert (only_run / "FINALNI_nabidka.docx").exists()
assert (only_run / "data/konfigurace/prompty/navrh.md").read_bytes() == (app_root / "prompts/draft.md").read_bytes()
```

Use the temporary app-root fixture and injected fakes; never point tests at the real `.env` or real output tree. Parameterize new proposal/policy/custom profiles and verify their final Czech/historical output tokens. Keep the existing cp1250/UTF-8 console, Ctrl+C, invalid-current-settings fallback, and latest-run selection regressions with English test names.
- [ ] **Step 2: Run failing tests.** Command: `.venv\Scripts\python.exe -m pytest tests/test_cli.py tests/test_application.py -q` after the mechanical module/import rename. Expected: new English-option assertions fail on unsupported arguments before implementation.
- [ ] **Step 3: Implement lifecycle and CLI translations.** Translate owned APIs and all remaining internals; normalize parser destinations and discovery filters to English IDs. Preserve current error recovery, raw-response filenames, consumption flushing, logger attachment/removal, browser-opening policy, and saved/current configuration rules. Technical log prose becomes English; user messages stay Czech. Update references to `run.bat`, `resume.bat`, `compare.bat`, `settings.yaml` and English key paths wherever the user is being told how to fix a problem. Keep report paths and final filenames Czech. Avoid blanket string replacements that alter quotations or output-path tokens.
- [ ] **Step 4: Rename and update Windows launchers.** `run.bat` calls `_setup.bat` then `python -m refiner`; `resume.bat` adds `--resume`; `compare.bat` adds `compare`. Translate batch labels, private variable names, comments, and the installer marker filename `requirements.nainstalovano` -> `requirements.installed` inside `.venv` (not generated application output). Keep Czech `echo` text, UTF-8 codepage, argument forwarding, working-directory setup, pause behavior and Python 3.10 check. Review file references and quoted paths statically; do not trigger dependency installation to test a rename.
- [ ] **Step 5: Update user/developer documentation with this deliverable.** Keep `README.md` Czech and revise source/config/material/command examples; its output table remains Czech-named. Put English setup, module overview, language boundary, legacy compatibility and offline test commands in `CONTRIBUTING.md`. Move the developer-only README section there and leave a Czech link. Document English-first materials/sidecar precedence and retained Czech CLI aliases. Update developer-only comments in metadata files only where needed; leave project name/version/dependency pins unchanged.
- [ ] **Step 6: Verify lifecycle and final behavior.** Rerun targeted CLI/application tests, the full suite, and `.venv\Scripts\python.exe -m refiner --help` (help must not require credentials or make calls). Expected: tests pass; help advertises English commands/options with Czech explanations. Use the test dry-run through `main` as the integration run so production `.env`, `input/`, and `output/` are untouched.
- [ ] **Step 7: User checkpoint.** Files: application/CLI/entry points, batch launchers, README/CONTRIBUTING, final translated test internals. Suggested message: `refactor: expose English entry points with Czech interaction`.

## Task 7: Audit language boundaries and verify the complete refactor

**Files:** Inspect all maintained paths in `refiner/`, `tests/`, `prompts/`, `profiles/`, root launchers/configuration/docs and `.gitignore`; modify only omissions identified by the audit. Preserve frozen legacy fixture payloads and all pre-existing private outputs.

**Interfaces:** Consumes the previous tasks' APIs and invariant tests. Produces verification evidence and a concise list of intentional Czech literals, grouped as user text, language patterns, preserved output paths, and compatibility mappings. Record this list in `CONTRIBUTING.md`, not in an additional localization framework or generated test suite.

- [ ] **Step 1: Audit maintained paths and Python APIs.** Run `rg --files refiner tests prompts profiles materials.example` and compare with the naming tables. Search `refiner` and `tests` with `rg -n 'fakta|konfigurace|pokracovat|nanecisto|nalezitosti|hodnoceni|posouzeni|spotreba|smycka|slozka|vysledek|nazev|zduvodneni|poptavka|podklady|prompty|profily' refiner tests`. Review hits by purpose, including unaccented identifiers and test names. Czech output-path strings, old aliases, fixtures and language content remain valid; Czech Python identifiers and developer explanations must be translated. Use file reads/search tools available in the harness, never perl/sed/awk.
- [ ] **Step 2: Check schema, template, configuration, and snapshot coverage.** Confirm every public model family has canonical English dump/schema keys, every prompt source is mapped and rendered, and both English root configuration and old snapshots load. Confirm no output writer emits `overview.html`, `comparison.html`, `FINAL_proposal.*`, English numbered filenames, or `data/configuration/`; the unchanged-output contract tests are the authority. Check source/snapshot bytes, report links, document exports, version-1 resume/compare and filled-form protection through the named tests rather than performing production model calls.
- [ ] **Step 3: Run final verification once after any audit fixes.** Run `.venv\Scripts\python.exe -m pytest -q`, `.venv\Scripts\python.exe -m compileall -q refiner`, and `git diff --check`. Expected: full suite passes with no new unexplained skips, compilation exits 0, tracked whitespace check exits 0. Because new files can be untracked, also inspect their content/whitespace directly; `git diff --check` alone does not cover them. Run `git diff --stat`, `git diff --name-status`, and `git status --short` for read-only scope review. Report pre-existing unrelated changes separately; never claim all checks passed without fresh output.
- [ ] **Step 4: Report and stop for the user.** Summarize renamed code/assets, unchanged Czech output behavior, legacy compatibility and exact verification counts/limitations. List the files in the final audit checkpoint and suggest `chore: verify English code and Czech output contracts`. Perform no Git writes and do not claim a real-provider or Windows-launcher end-to-end run was performed when verification used mocks/static review.

## Self-review and execution handoff

Coverage: Tasks 1/3 pin the unchanged output tree and asset/snapshot mapping; Task 2 covers input/provider behavior; Task 4 covers English schemas, saved-run migration and prompts; Task 5 covers Czech rendering/comparison; Task 6 covers entry points and documentation; Task 7 audits the entire boundary. All five Review Focus risks have owning tests. Public signatures and field names above are the cross-task contract; tasks update callers in the same change. No skill creation, worktree, dependency update, private-data rewrite or Git write is required.

Recommended execution: **Native**, using the local `executing-plans` skill and the current checkout, with one fresh-context independent review at the end. This refactor's stages share data fields, imports and prompt contracts, so keeping one implementation context avoids repeated rediscovery. The alternative is **Subagent-driven**, with a fresh implementer/reviewer per task; select it only if the user prefers that review cadence. Both methods obey the user's no-Git rules and mandatory stops at commit-equivalent checkpoints; these user instructions override a skill's default continuous execution.

Do not implement as part of writing this plan. Ask the user to review the plan and choose an execution method. The invoked writing-plans skill requires this handoff before implementation. At each later user checkpoint, stop with file groups and the suggested message; continue only within the user's execution authorization.

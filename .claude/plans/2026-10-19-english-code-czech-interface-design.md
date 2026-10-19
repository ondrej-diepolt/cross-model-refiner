# English code, Czech user interface

Date: 2026-10-19
Status: Approved by the user on 2026-10-19; implementation planning requested.

Builder check: An independent software-engineering reviewer reported
"nothing important left" on 2026-10-19, including a second check after the user's
correction to preserve generated output filenames.

## Intent and decisions

An English-speaking programmer should be able to understand and maintain the
implementation without knowing Czech. A Czech-speaking user should be able to
operate the application and read its documents without knowing English.

The user explicitly requested English code, including filenames and class names,
while retaining Czech output, messages, and interactive choices. They clarified
that implementation filenames must become English even when users launch those
files directly. For example, `spustit.bat` becomes `run.bat`, but its messages
remain Czech. They subsequently clarified that generated output filenames must
retain their current Czech names. This applies to new and existing runs alike.

This is a repository-wide naming and documentation refactor, not a change to the
document generation workflow. It warrants a written design and implementation plan.
No product code has been changed as part of this design.

## Current application

The Python package `refiner` accepts a request and company supporting materials.
Claude extracts requirements and drafts a document, GPT evaluates it, and Claude
reviews and incorporates suggested improvements. Deterministic code calculates
scores and chooses the final version. The application exports Czech Markdown,
DOCX, differences, and an HTML overview. A separate comparison workflow evaluates
the result against a reference document.

Configuration and prompts are editable YAML and Markdown files. Every run stores
its state, step outputs, token usage, and copies of configuration and prompts.
Interrupted runs resume without repeating successful steps. Resume uses current
model settings and prices but retains the saved scoring configuration and prompts.
Comparison uses current comparison prompts and the saved evaluation prompt.

Czech identifiers occur throughout source, tests, schema fields, enum values,
templates, configuration, prompt placeholders, filenames, and saved state.
Renaming only Python files would leave most of the maintenance problem intact.

## Language boundary

### English implementation and technical names

- All maintained source and test filenames, package directories, modules, imports,
  classes, methods, functions, arguments, variables, constants, and fixtures.
- Comments and docstrings explaining implementation, including batch comments.
- Internal dictionary keys, state and step identifiers, enum values, template
  context names, prompt placeholders, JSON schema keys, and schema titles.
- Repository configuration filenames and keys, internal profile identifiers,
  source prompt filenames, and source template filenames. Generated output paths
  are explicitly excluded from this renaming.
- Canonical CLI command and option names: `compare`, `--resume`, `--dry-run`.
- Developer-authored technical log messages and developer documentation.

### Czech language content

- Console messages, questions, choices, progress, warnings, errors, CLI help, and
  usage explanations. Command, option, filename, and key references use their
  actual spelling: English for renamed implementation assets and Czech for
  preserved generated outputs.
- Generated document text, report labels, tables, explanations, comparison
  questionnaires, and all human-readable model responses.
- All generated output filenames and run-directory paths, including numbered
  documents, final exports, reports, differences, JSON files, logs, and saved
  configuration/prompt filenames. Preserve the existing naming conventions.
- Prompt prose and examples, profile display names, criterion names/descriptions,
  document structure instructions, and user-facing configuration explanations.
- The Czech user guide in `README.md` and company profile example contents.
- `[DOPLNIT: …]`, Czech text-matching patterns, currency and number formatting,
  Czech names and quotations supplied in input, and language-sensitive test data.

A repository implementation filename is English even when a user sees it;
generated output filenames retain their current Czech names. Text inside a file
is classified by its purpose. For example, repository `settings.yaml` has English
keys and Czech comments explaining them; source `prompts/evaluation.md` has Czech
instructions using English schema keys and `${request}` placeholders.

The configuration-key, CLI-token, and prompt-language rules above are proposed
implementation choices inferred from the user's intent. Preserving generated
output filenames is an explicit user requirement.

## Naming vocabulary

Use ordinary English consistently. Distinguish a document draft from an evaluator's
revision suggestion, and an evaluation from the author's review of suggestions.

| Existing path | Proposed path |
|---|---|
| `refiner/aplikace.py` | `refiner/application.py` |
| `refiner/beh.py` | `refiner/run.py` |
| `refiner/fakta.py` | `refiner/facts.py` |
| `refiner/konfigurace.py` | `refiner/configuration.py` |
| `refiner/kroky.py` | `refiner/steps.py` |
| `refiner/smycka.py` | `refiner/loop.py` |
| `refiner/skore.py` | `refiner/scoring.py` |
| `refiner/vstup.py` | `refiner/input.py` |
| `refiner/porovnani.py` | `refiner/comparison.py` |
| `refiner/modely/` | `refiner/models/` |
| `modely/rozhrani.py` | `models/interface.py` |
| `modely/podproces.py` | `models/subprocess.py` |
| `modely/falesne.py` | `models/fakes.py` |
| `modely/chyby.py` | `models/errors.py` |
| `refiner/vystup/` | `refiner/output/` |
| `vystup/prehled.py` | `output/overview.py` |
| `vystup/sablony/` | `output/templates/` |
| `tests/pomocne.py` | `tests/helpers.py` |
| `nastaveni.yaml` | `settings.yaml` |
| `profily/nabidka.yaml` | `profiles/proposal.yaml` |
| `profily/smernice.yaml` | `profiles/policy.yaml` |
| `prompty/` | `prompts/` |
| `podklady.priklad/profil_firmy.md` | `materials.example/company_profile.md` |
| `spustit.bat` | `run.bat` |
| `pokracovat.bat` | `resume.bat` |
| `porovnat.bat` | `compare.bat` |
| `_priprava.bat` | `_setup.bat` |

Already-English paths such as `cli.py`, `data.py`, `docx.py`, and `diff.py` stay as
they are. Test module names follow their renamed implementation modules.

Examples of symbol translations: `Beh` -> `Run`, `StavBehu` -> `RunState`,
`Konfigurace` -> `Configuration`, `Nalezitost` -> `Requirement`, `Hodnoceni` ->
`Evaluation`, `Navrh` -> `RevisionSuggestion`, `Posouzeni` -> `SuggestionReview`,
`Spotreba` -> `TokenUsage`, `najdi_placeholdery` -> `find_placeholders`.

Use `request`, `materials`, `requirements`, `draft`, `evaluation`, `suggestion`,
`review`, and `revision` for their respective concepts. `proposal` is the document
type currently identified as `nabidka`; its display name remains `Nabídka`, and
its output filename token remains `nabidka`. Likewise, internal `policy` retains
the output token `smernice`. Keep the output token separate from the English
internal identifier so final filenames do not change. Preserve existing custom
profile output tokens as well.

## Configuration, prompts, schemas, and rendering

English field names are canonical in Python, new YAML, new JSON, and new model
schemas. Internal values become English, for example `running`, `completed`,
`interrupted`, `high`, `medium`, `low`, `accepted`, `partial`, and `rejected`.
Do not use translated internal tokens directly as user-facing labels. Map them
explicitly to Czech at rendering boundaries, including priorities, coverage,
comparison verdicts, suspicious fact types, and run status.

Update prompt references to schema fields, enum tokens, and placeholders together
with their producers. Keep the surrounding Czech instructions and all substantive
generation/scoring rules unchanged. Human-readable response fields must contain
Czech text even though their JSON keys are English. Maintain schema restrictions
required by the existing providers.

Keep user-facing validation explanations Czech. Validation paths must point to the
actual English key in a new file or Czech key in a legacy file, with correct line
numbers. Do not accidentally expose an English internal enum as the only explanation
of an interactive choice.

Generated files retain their existing names for both new and existing runs:
`prehled.html`, `FINALNI_nabidka.md`, `FINALNI_nabidka.docx`,
`FINALNI_smernice.*`, `01_poptavka.md`, `02_nalezitosti.md`, `03_navrh_v1.md`,
`04_hodnoceni_1.md`, `05_posouzeni_1.md`, `*_zmeny.html`, `porovnani.html`,
and `porovnani_formular.md`. Preserve step numbering and all remaining naming
patterns. Technical files and directories also retain their names, including
`data/beh.json`, `data/beh.log`, `data/podklady.md`, `data/konfigurace/`,
`data/porovnani*.json`, and `data/surova_odpoved*.txt`.

Saved configuration and prompt copies keep the existing output layout and names,
including `nastaveni.yaml`, `profil.yaml`, `kriteria.yaml`, and `prompty/*.md`
under `data/konfigurace/`. Map renamed source assets explicitly to these saved
names, including refreshed comparison prompts; do not copy the English source
directory layout into the run. New snapshots still contain the exact configuration
and prompt content actually used, with English technical keys/placeholders.

Use English-named constants and functions to define or resolve these Czech output
path strings. Source `output/templates/overview.html.j2` can render to generated
`prehled.html`; source `settings.yaml` is saved as
`data/konfigurace/nastaveni.yaml`. Czech path literals are part of the preserved
output contract, not untranslated code identifiers.

All generated links, console references, and README examples must use the preserved
output filenames. Input-derived run folder names keep their original title or slug.

## Existing data and compatibility

Preserving resumable work is a proposed engineering safeguard: the user did not
request discarding existing runs. Keep compatibility narrowly at file-loading,
prompt-rendering, and serialization boundaries; do not retain Czech Python APIs
or duplicate implementation modules.

- Maintained repository assets and new serialized technical fields use English.
  Output filenames and directories retain their existing Czech naming conventions.
- Support opening, discovering, resuming, and comparing existing runs whose state
  is in `data/beh.json`, including Czech fields, enum values, step keys, profile
  identifiers, saved configuration paths, and prompt filenames/placeholders.
- Normalize legacy fields and identifiers into the English in-memory models.
  Preserve recorded artifact paths verbatim so existing files remain accessible.
  Decode old per-step JSON at the read boundary rather than rewriting all outputs.
- Record a format version in new state. A missing version identifies legacy state.
  Keep `data/beh.json` as the state filename for every run; its new contents can
  use English fields. Determine legacy payloads by version, not by filename.
  Never create an additional English-named state file.
- Legacy saved prompts must still render. Supply legacy placeholder aliases when
  rendering those templates, and decode legacy response field/enum names where
  their saved instructions require them. New prompt templates use English tokens.
  English schema keys do not require changing the substance of the Czech prompt.
- Keep frozen scoring criteria and prompt semantics on resume. Current model
  settings and prices still come from repository `settings.yaml`. Comparison
  retains its existing current-prompt versus saved-prompt policy.
- Keep `porovnani_formular.md` for every run and protect existing filled-in answers
  when comparison is repeated.
- Accept existing Czech CLI spellings as compatibility aliases; advertise the
  English spellings in new launchers and documentation. Do not keep old tracked
  batch files as duplicate launchers.
- New supporting materials use `materials/`, with optional `template.docx` and
  `company_profile.md`. Read a pre-existing private `podklady/` directory as a
  fallback, including `sablona.docx`, without moving or modifying user documents.
  Prefer `materials/` when present; do not silently combine both directories.
- Recognize existing `*.kriteria.yaml` sidecars as a fallback for new
  `*.criteria.yaml` files. Prefer the English name if both exist.
- Preserve current settings and profile values while translating their structure.
  Update ignore rules for the new private-materials directory.

The builder may choose explicit legacy converters or Pydantic validation aliases,
but English must remain canonical in new serialization and generated schemas.
Any remaining Czech technical names must be clearly confined to preserved output
path strings and output profile tokens, compatibility mappings, Czech language
content, or original user data.

## Documentation and scope limits

Keep the README user instructions Czech and update renamed implementation assets
and commands while retaining all current generated-output names.
Provide English developer setup, architecture, naming-boundary, and verification
notes in `CONTRIBUTING.md`; move the current developer-only README section there
and leave a brief Czech link in the README. This is a proposed documentation choice.

Do not translate historical design/plan files, user documents, existing generated
output, third-party code, virtual environments, caches, provider identifiers, or
secrets. Do not read or edit `.env` as part of translation. Update `.env.example`
only if it contains developer-facing prose needing translation; user setup guidance
remains Czech.

Do not change models, prices, retries, authentication, network isolation, process
cleanup, extraction rules, scoring, revision limits, or document structure.
Avoid restructuring unrelated code or introducing a localization framework.
Translate developer explanations without changing their technical meaning.

Work in the current checkout. Do not commit, push, merge, rebase, create a PR, or
create a worktree. Preserve unrelated changes. Designs and plans belong under
`.claude/plans/`. No task in this design creates or rewrites a skill.

## Acceptance and verification

1. Run the existing offline test suite before changes and preserve its behavior
   while translating test names, fixtures, helpers, imports, and technical values.
2. Run the full suite after the refactor. It must continue blocking network access
   and real Claude/Codex processes; update those interception paths with imports.
3. Add focused behavior checks for newly introduced compatibility: a representative
   interrupted legacy run resumes without repeating completed calls, a completed
   legacy run compares correctly, and user answers in an existing form survive.
4. Verify English new configuration/schema fields and valid prompt substitutions.
   Check Czech enum labels and representative console/error/report text rather
   than testing every mechanical identifier rename.
5. Exercise an offline dry run through the English CLI, including resume and the
   fake comparison path through tests; production comparison still rejects demo
   runs. Verify English implementation filenames, unchanged Czech output filenames
   and directory layout, Czech contents, report links, and DOCX export. Check that
   new `proposal` and `policy` profiles still export `FINALNI_nabidka.*` and
   `FINALNI_smernice.*`, and that saved prompt copies retain their current paths.
6. Review renamed batch launchers and shared setup references. Avoid launching
   real providers or installing dependencies merely to verify translations.
7. Audit source and tests for Czech identifiers/comments/docstrings, including
   unaccented Czech. Treat Czech strings individually by purpose; a blanket ban on
   Czech text would break the required interface and language matching.
8. Report verification evidence and any limitations. Supply checkpoint file groups
   and suggested commit messages for the user; perform no Git writes.

## Decisions left to the builder

Choose precise secondary identifier names consistent with the vocabulary above,
the smallest safe compatibility implementation, and meaningful test fixtures that
contain no private user data. Split the implementation plan into reviewable stages
without promising that temporarily half-renamed modules are runnable.

Approval covers the full language boundary and compatibility behavior described
here. After approval, use the writing-plans skill to create the implementation plan
under `.claude/plans/`; implementation is a subsequent step.

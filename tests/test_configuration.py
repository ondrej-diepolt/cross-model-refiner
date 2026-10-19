import textwrap

import pytest

from refiner.configuration import (
    ConfigurationError,
    criteria_path_for_request,
    available_profiles,
    load_configuration,
    load_settings,
)

SETTINGS = """\
models:
  claude: {model: c, effort: high, extraction_effort: medium, max_tokens_text: 10, max_tokens_json: 5, fallback: true}
  gpt: {model: g, effort: high, max_output_tokens: 10}
  max_retries: 4
  timeout_s: 600
loop: {target_score: 9.5, max_revisions: 3, min_requirement_score: 8, max_suggestions: 10}
group_weights: {A: 0.5, B: 0.35, C: 0.15}
default_profile: proposal
prices_usd_per_million:
  c: {input: 1.0, output: 2.0}
"""


def _write(path, text):
    path.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    return path


def _profile(tmp_path, criteria=None, header=None):
    header = header or "name: P\ndocument_type: x\nstructure_instructions: osnova\n"
    criteria = criteria or (
        "criteria:\n"
        "  - id: B1\n    name: Prvni\n    description: p\n    weight: 0.5\n"
        "  - id: B2\n    name: Druhe\n    description: p\n    weight: 0.5\n"
    )
    return _write(tmp_path / "profile.yaml", header + criteria)


def _settings(tmp_path, replacements=None):
    text = SETTINGS
    for a, b in (replacements or {}).items():
        assert a in text
        text = text.replace(a, b)
    return _write(tmp_path / "settings.yaml", text)


def test_loads_repository_configuration(repo_root):
    k = load_configuration(repo_root / "settings.yaml", repo_root / "profiles" / "proposal.yaml")
    assert k.settings.loop.target_score == 9.5 and k.settings.loop.max_revisions == 3
    assert k.settings.models.claude.model == "claude-opus-5-5"
    # Reasoning counts toward output limits; low limits caused truncated responses.
    assert k.settings.models.claude.max_tokens_json == 32000
    assert k.settings.models.gpt.max_output_tokens == 64000 and k.settings.models.timeout_s == 1800
    assert [c.id for c in k.profile_criteria] == ["B1", "B2", "B3", "B4", "B5", "B6"]
    assert k.profile_id == "proposal"


def test_text_weight_reports_file_line_and_czech_message(tmp_path):
    profile = _write(
        tmp_path / "profile.yaml",
        """\
        name: P
        document_type: x
        structure_instructions: osnova
        criteria:
          - id: B1
            name: Prvni
            description: p
            weight: 0.5
          - id: B2
            name: Druhe
            description: p
            weight: vysoká
        """,
    )
    with pytest.raises(ConfigurationError) as e:
        load_configuration(_settings(tmp_path), profile)
    assert "profile.yaml" in str(e.value) and "řádek 12" in str(e.value)
    assert "musí být číslo" in str(e.value) and "vysoká" in str(e.value)


def test_unknown_key_typo(tmp_path):
    profile = _profile(
        tmp_path,
        header="name: P\ndocument_type: x\nstructure_instructions: o\nkriterja: []\n",
        criteria="criteria: []\n",
    )
    with pytest.raises(ConfigurationError) as e:
        load_configuration(_settings(tmp_path), profile)
    assert "neznámá položka" in str(e.value) and "kriterja" in str(e.value)


def test_missing_required_key(tmp_path):
    settings = _settings(tmp_path, {"target_score: 9.5, ": ""})
    with pytest.raises(ConfigurationError) as e:
        load_configuration(settings, _profile(tmp_path))
    assert "chybí povinná položka" in str(e.value) and "target_score" in str(e.value)
    assert "settings.yaml" in str(e.value)


@pytest.mark.parametrize("original,typo,path", [
    ("claude: {model: c, effort: high", "claude: {model: c, effort: hihg", "models.claude.effort"),
    ("extraction_effort: medium", "extraction_effort: stredni", "models.claude.extraction_effort"),
    ("gpt: {model: g, effort: high", "gpt: {model: g, effort: maximum", "models.gpt.effort"),
    # Only OpenAI accepts minimal effort; Anthropic does not.
    ("claude: {model: c, effort: high", "claude: {model: c, effort: minimal", "models.claude.effort"),
])
def test_invalid_effort_reports_in_czech(tmp_path, original, typo, path):
    settings = _settings(tmp_path, {original: typo})
    with pytest.raises(ConfigurationError) as e:
        load_configuration(settings, _profile(tmp_path))
    message = str(e.value)
    assert "settings.yaml, řádek" in message and path in message
    assert "musí být jedna z" in message and "'xhigh' nebo 'max'" in message
    assert " or " not in message


def test_sdk_effort_values(tmp_path):
    settings = _settings(tmp_path, {"claude: {model: c, effort: high": "claude: {model: c, effort: xhigh",
                                 "gpt: {model: g, effort: high": "gpt: {model: g, effort: minimal"})
    k = load_configuration(settings, _profile(tmp_path))
    assert k.settings.models.claude.effort == "xhigh"
    assert k.settings.models.gpt.effort == "minimal"


def test_group_weights_must_sum_to_one(tmp_path):
    settings = _settings(tmp_path, {"{A: 0.5, B: 0.35, C: 0.15}": "{A: 0.5, B: 0.5, C: 0.15}"})
    with pytest.raises(ConfigurationError) as e:
        load_configuration(settings, _profile(tmp_path))
    assert "součet" in str(e.value)


def test_invalid_yaml_reports_line(tmp_path):
    profile = _write(tmp_path / "profile.yaml", "name: P\nkriteria: [a, b\ntyp: x\n")
    with pytest.raises(ConfigurationError) as e:
        load_configuration(_settings(tmp_path), profile)
    assert "řádek" in str(e.value) and "profile.yaml" in str(e.value)


def test_request_criteria_add_and_reweight(tmp_path, repo_root):
    kr = _write(
        tmp_path / "a.criteria.yaml",
        """\
        extra_criteria:
          - id: X1
            name: Navic
            description: p
            weight: 0.1
        weights: {B6: 0.05}
        """,
    )
    k = load_configuration(repo_root / "settings.yaml", repo_root / "profiles" / "proposal.yaml", kr)
    ids = [c.id for c in k.profile_criteria]
    assert ids[-1] == "X1"
    assert next(c for c in k.profile_criteria if c.id == "B6").weight == 0.05
    assert [c.id for c in k.profile.criteria] == ["B1", "B2", "B3", "B4", "B5", "B6"]
    assert next(c for c in k.profile.criteria if c.id == "B6").weight == 0.10


def test_request_criteria_unknown_weight_id(tmp_path, repo_root):
    kr = _write(tmp_path / "a.criteria.yaml", "weights: {B9: 0.1}\n")
    with pytest.raises(ConfigurationError) as e:
        load_configuration(repo_root / "settings.yaml", repo_root / "profiles" / "proposal.yaml", kr)
    assert "B9" in str(e.value)


def test_criterion_id_cannot_start_with_N(tmp_path):
    profile = _profile(
        tmp_path,
        criteria="criteria:\n  - id: N1\n    name: A\n    description: p\n    weight: 1\n",
    )
    with pytest.raises(ConfigurationError) as e:
        load_configuration(_settings(tmp_path), profile)
    assert "N" in str(e.value) and "vyhrazen" in str(e.value)


def test_duplicate_criterion_id(tmp_path):
    profile = _profile(
        tmp_path,
        criteria=(
            "criteria:\n"
            "  - id: B1\n    name: A\n    description: p\n    weight: 1\n"
            "  - id: B1\n    name: B\n    description: p\n    weight: 1\n"
        ),
    )
    with pytest.raises(ConfigurationError) as e:
        load_configuration(_settings(tmp_path), profile)
    assert "duplicitní" in str(e.value) and "B1" in str(e.value)


def test_criteria_path_for_request(tmp_path):
    input = tmp_path / "a.docx"
    input.write_bytes(b"")
    assert criteria_path_for_request(input) is None
    kr = _write(tmp_path / "a.criteria.yaml", "weights: {}\n")
    assert criteria_path_for_request(input) == kr


def test_available_profiles(repo_root):
    assert available_profiles(repo_root / "profiles") == ["proposal", "policy"]


def test_default_mode_is_subscription(repo_root):
    n = load_settings(repo_root / "settings.yaml")
    assert n.models.mode == "subscription"
    assert n.models.subscription.claude.model == "claude-opus-5-5"
    assert n.models.subscription.codex.model == "gpt-6-astra"
    assert n.models.subscription.claude.command is None


def test_legacy_snapshot_without_mode_loads(legacy_settings):
    text = legacy_settings.read_text(encoding="utf-8")
    assert "  rezim: predplatne\n" in text
    legacy_settings.write_text(text.replace("  rezim: predplatne\n", ""), encoding="utf-8")
    n = load_settings(legacy_settings)
    assert n.models.mode == "subscription" and n.models.subscription.codex.effort == "high"


@pytest.mark.parametrize("effort", ["ultra", "none", "minimal"])
def test_invalid_codex_effort_fails(tmp_path, effort):
    file = _settings(tmp_path, {"models:\n": f"models:\n  subscription: {{codex: {{effort: {effort}}}}}\n"})
    with pytest.raises(ConfigurationError, match="models.subscription.codex.effort"):
        load_settings(file)


def test_unknown_mode_fails(tmp_path):
    file = _settings(tmp_path, {"models:\n": "models:\n  mode: xyz\n"})
    with pytest.raises(ConfigurationError, match="models.mode"):
        load_settings(file)


def test_subscription_extraction_effort_applies_to_claude(tmp_path):
    """Steps read models.claude.extraction_effort; subscription mode uses the subscription value."""
    file = _settings(tmp_path, {"models:\n": "models:\n  subscription: {claude: {extraction_effort: low}}\n"})
    n = load_settings(file)
    assert n.models.claude.extraction_effort == "low"


def test_api_extraction_effort_is_preserved(tmp_path):
    file = _settings(tmp_path, {"models:\n": "models:\n  mode: api\n  subscription: {claude: {extraction_effort: low}}\n"})
    assert load_settings(file).models.claude.extraction_effort == "medium"


@pytest.fixture
def english_settings(tmp_path):
    return _write(tmp_path / "english.yaml", """\
        models:
          claude: {model: c, effort: high, extraction_effort: medium, max_tokens_text: 10, max_tokens_json: 5, fallback: true}
          gpt: {model: g, effort: high, max_output_tokens: 10}
          max_retries: 4
          timeout_s: 600
        loop: {target_score: 9.5, max_revisions: 3, min_requirement_score: 8, max_suggestions: 10}
        group_weights: {A: 0.5, B: 0.35, C: 0.15}
        default_profile: proposal
        prices_usd_per_million:
          c: {input: 1.0, output: 2.0}
        """)


@pytest.fixture
def legacy_settings(tmp_path, repo_root):
    path = tmp_path / "legacy.yaml"
    path.write_bytes((repo_root / "tests/fixtures/legacy/completed/data/konfigurace/nastaveni.yaml").read_bytes())
    return path


def test_english_and_legacy_settings_use_canonical_fields(english_settings, legacy_settings):
    from refiner.configuration import Settings, load_settings

    for path in (english_settings, legacy_settings):
        settings = load_settings(path)
        assert settings.models.mode == "subscription"
        assert settings.default_profile == "proposal"
        assert "models" in settings.model_dump() and "modely" not in settings.model_dump()
    assert "models" in Settings.model_json_schema()["properties"]
    assert "modely" not in Settings.model_json_schema()["properties"]


@pytest.mark.parametrize("legacy", [False, True])
def test_invalid_weight_reports_actual_source_key_and_line(tmp_path, english_settings, legacy):
    from refiner.configuration import ConfigurationError, load_configuration

    keys = ("nazev", "typ_dokumentu", "pokyny_struktura", "kriteria", "vaha", "popis") if legacy else (
        "name", "document_type", "structure_instructions", "criteria", "weight", "description")
    name, document_type, structure, criteria, weight, description = keys
    profile = tmp_path / "invalid.yaml"
    profile.write_text(
        f"{name}: P\n{document_type}: x\n{structure}: osnova\n{criteria}:\n"
        f"  - id: B1\n    {weight}: vysoká\n    {name}: První\n    {description}: p\n", encoding="utf-8")
    with pytest.raises(ConfigurationError) as caught:
        load_configuration(english_settings, profile)
    message = str(caught.value)
    assert "invalid.yaml" in message and "řádek 6" in message
    assert f"{criteria}.0.{weight}" in message and "musí být číslo" in message


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("weights,detail", [("B1: 0", "musí být větší než 0"), ("UNKNOWN: 1", "neznámé ID")])
def test_sidecar_validation_reports_actual_weight_key(tmp_path, english_settings, legacy, weights, detail):
    from refiner.configuration import ConfigurationError, load_configuration

    profile = _profile(tmp_path)
    key = "vahy" if legacy else "weights"
    sidecar = _write(tmp_path / "invalid.criteria.yaml", f"{key}: {{{weights}}}\n")
    with pytest.raises(ConfigurationError) as caught:
        load_configuration(english_settings, profile, sidecar)
    message = str(caught.value)
    assert "řádek 1" in message and f"{key}.{weights.split(':')[0]}" in message and detail in message


def test_english_sidecar_precedes_legacy_without_combining(tmp_path, english_settings):
    from refiner.configuration import criteria_path_for_request, load_configuration

    request = tmp_path / "request.md"
    old = request.with_suffix(".kriteria.yaml")
    old.write_text("vahy: {B1: 9}\n", encoding="utf-8")
    assert criteria_path_for_request(request) == old
    current = request.with_suffix(".criteria.yaml")
    current.write_text("weights: {B1: 2}\n", encoding="utf-8")
    selected = criteria_path_for_request(request)
    assert selected == current
    configuration = load_configuration(english_settings, _profile(tmp_path), selected)
    assert configuration.profile_criteria[0].weight == 2
    assert old.read_text(encoding="utf-8") == "vahy: {B1: 9}\n"

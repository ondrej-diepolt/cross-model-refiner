"""Stable Czech artifact names, independent of English source asset names."""

STATE_FILE = "data/beh.json"
LOG_FILE = "data/beh.log"
CONFIGURATION_DIRECTORY = "data/konfigurace"
MATERIALS_FILE = "data/podklady.md"
OVERVIEW_FILE = "prehled.html"
COMPARISON_FILE = "porovnani.html"
COMPARISON_FORM = "porovnani_formular.md"

PROMPT_SNAPSHOT_NAMES: dict[str, str] = {
    "requirements": "nalezitosti.md",
    "draft": "navrh.md",
    "evaluation": "hodnoceni.md",
    "review": "posouzeni.md",
    "revision": "zapracovani.md",
    "comparison_criteria": "porovnani_kriteria.md",
    "comparison_elements": "porovnani_prvky.md",
    "comparison_coverage": "porovnani_pokryti.md",
}


def canonical_profile_id(profile_id: str) -> str:
    return {"nabidka": "proposal", "smernice": "policy"}.get(profile_id, profile_id)


def output_profile_name(profile_id: str) -> str:
    return {"proposal": "nabidka", "policy": "smernice"}.get(profile_id, profile_id)

"""Decode historical technical identifiers without changing saved files or user text."""
from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from refiner.artifacts import canonical_profile_id

PRIORITIES = {"vysoka": "high", "stredni": "medium", "nizka": "low"}
DECISIONS = {"prijato": "accepted", "castecne": "partial", "odmitnuto": "rejected"}
STATUSES = {"bezi": "running", "dokoncen": "completed", "prerusen": "interrupted"}
STOP_REASONS = {"cil_splnen": "target_reached", "limit_revizi": "revision_limit", "zadna_zmena": "no_changes"}
BETTER_VALUES = {"stejne": "tie"}
COVERAGE_STATUSES = {"je": "present", "castecne": "partial", "chybi": "missing"}
VERDICTS = {"generovana": "generated", "reference": "reference", "nerozhodne": "tie"}

STEP_IDS = {
    "poptavka": "request", "nalezitosti": "requirements",
    "porovnani_kalibrace": "comparison_calibration",
    "porovnani_srovnani_1": "comparison_pair_1", "porovnani_srovnani_2": "comparison_pair_2",
    "porovnani_prvky": "comparison_elements", "porovnani_pokryti": "comparison_coverage",
}


def normalize_step_id(step: str) -> str:
    match = re.fullmatch(r"(navrh|hodnoceni|posouzeni)_(\d+)", step)
    if match:
        prefix = {"navrh": "draft", "hodnoceni": "evaluation", "posouzeni": "review"}[match[1]]
        return f"{prefix}_{match[2]}"
    return STEP_IDS.get(step, step)


def _rename_fields(value: Mapping[str, Any], aliases: dict[str, str]) -> dict[str, Any]:
    result = dict(value)
    for old, new in aliases.items():
        if old in result:
            result.setdefault(new, result.pop(old))
    return result


def normalize_run_state(value: Any) -> Any:
    """Upgrade only known state fields; per-step payloads retain their own typed readers."""
    if not isinstance(value, Mapping):
        return value
    version = value.get("schema_version", 1)
    if type(version) is not int or version not in (1, 2):
        raise ValueError("Nepodporovaná verze stavu běhu.")
    result = _rename_fields(value, {
        "vstup": "input", "profil": "profile_id", "vytvoreno": "created_at",
        "nanecisto": "dry_run", "ukonceno": "ended_at", "stav": "status",
        "duvod_ukonceni": "stop_reason", "chyba": "error", "finalni_verze": "final_version",
        "kroky": "steps", "skore": "scores", "spotreba": "usage", "varovani": "warnings",
    })
    if version == 1 and isinstance(result.get("profile_id"), str):
        historical_token = result["profile_id"]
        result["profile_id"] = canonical_profile_id(historical_token)
        result.setdefault("output_profile_name", historical_token)
    result["schema_version"] = 2
    if isinstance(result.get("status"), str):
        result["status"] = STATUSES.get(result["status"], result["status"])
    if isinstance(result.get("stop_reason"), str):
        result["stop_reason"] = STOP_REASONS.get(result["stop_reason"], result["stop_reason"])
    if isinstance(result.get("steps"), Mapping):
        result["steps"] = {
            normalize_step_id(key): _rename_fields(record, {"cislo": "number", "soubor": "file"})
            if isinstance(record, Mapping) else record
            for key, record in result["steps"].items()
        }
    if isinstance(result.get("usage"), list):
        result["usage"] = []
        for item in value.get("usage", value.get("spotreba", [])):
            if isinstance(item, Mapping):
                item = _rename_fields(item, {
                    "krok": "step", "vstup": "input_tokens", "vystup": "output_tokens",
                    "cache_cteni": "cache_read_tokens", "cache_zapis": "cache_write_tokens",
                    "predplatne": "subscription",
                })
                if isinstance(item.get("step"), str):
                    item["step"] = normalize_step_id(item["step"])
            result["usage"].append(item)
    return result


PROMPT_VARIABLES = {
    "poptavka": "request", "podklady": "materials", "typ_dokumentu": "document_type",
    "nalezitosti": "requirements", "pokyny_struktura": "structure_instructions",
    "kriteria": "criteria", "max_navrhu": "max_suggestions", "odmitnute": "rejected_suggestions",
}

PROMPT_FIELDS = {
    "requirements": {"nalezitosti": "requirements", "citace": "citation"},
    "evaluation": {
        "kriteria": "criteria", "skore": "score", "zduvodneni": "rationale", "dukaz": "evidence",
        "vymyslena_fakta": "fabricated_facts", "tvrzeni_k_overeni": "claims_to_verify",
        "citace": "citation", "proc": "reason", "navrhy": "suggestions", "kriterium": "criterion",
        "misto": "location", "navrh": "suggestion", "priorita": "priority",
        "celkovy_komentar": "overall_comment", **PRIORITIES,
    },
    "review": {
        "rozhodnuti": "decisions", "rozhodnuti[].rozhodnuti": "decisions[].decision",
        "id_navrhu": "suggestion_id", "opora": "support", "predpoklad": "assumption",
        "dusledek": "consequence", "zduvodneni": "rationale", "jak_zapracovat": "implementation",
        "shrnuti": "summary", **DECISIONS,
    },
    "comparison_criteria": {"kriteria": "criteria", "lepsi": "better", "zduvodneni": "rationale", **BETTER_VALUES},
    "comparison_elements": {"prvky": "elements", "popis": "description"},
    "comparison_coverage": {"polozky": "items", "stav": "status", "komentar": "comment", **COVERAGE_STATUSES},
}


def adapt_legacy_prompt(text: str, name: str) -> str:
    """Append a schema clarification to old instructions, without rewriting their prose.

    Detection uses tokens in the content: a Czech snapshot basename can also contain
    a new canonical prompt. Text-only draft/revision prompts need no schema note.
    """
    fields = PROMPT_FIELDS.get(name)
    if not fields:
        return text
    old_variables = any("${" + key + "}" in text for key in PROMPT_VARIABLES)
    old_fields = any(re.search(r"`[^`\n]*\b" + re.escape(key) + r"\b[^`\n]*`", text) for key in fields)
    if not old_variables and not old_fields:
        return text
    mappings = "\n".join(f"- {old} → {new}" for old, new in fields.items())
    return (text + "\n\n## Technické názvy polí\n\n"
            "Původní věcné pokyny výše platí. Pro strukturovanou odpověď použij přiložené schéma "
            "s anglickými názvy polí a hodnotami. Technické názvy uvedené výše čti takto:\n"
            + mappings + "\n")


def prompt_variables(variables: dict[str, str]) -> dict[str, str]:
    """Expose old placeholders only while rendering a saved template."""
    return {**{old: variables[new] for old, new in PROMPT_VARIABLES.items() if new in variables}, **variables}

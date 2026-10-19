"""Deterministic fact checks: placeholders and details absent from the sources."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

_PLACEHOLDER = re.compile(r"\[DOPLNIT(?::([^\]]*))?\]")

_UPPERCASE = "A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ"
_LOWERCASE = "a-záčďéěíňóřšťúůýž"

# Order only affects output; each kind is matched independently.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ('amount', re.compile(r"\d{1,3}(?:[  .]\d{3})*(?:,\d+)?\s?(?:Kč|CZK)")),
    ('company_id', re.compile(r"\b\d{8}\b")),
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ('phone', re.compile(r"(?:\+420[  ]?)?\d{3}[  ]?\d{3}[  ]?\d{3}")),
    ('name', re.compile(
        rf"\b(?:Ing|Mgr|Bc|JUDr|PhDr|RNDr|MUDr|doc|prof)\.\s+[{_UPPERCASE}][{_LOWERCASE}]+"
        rf"(?:\s+[{_UPPERCASE}][{_LOWERCASE}]+)?")),
    ("url", re.compile(r"https?://\S+")),
]


class SuspiciousFact(BaseModel):
    kind: Literal['amount', 'company_id', "email", 'phone', 'name', "url"]
    value: str


def find_placeholders(md: str) -> list[str]:
    seen: list[str] = []
    for m in _PLACEHOLDER.finditer(md):
        content = (m.group(1) or "").strip()
        if content not in seen:
            seen.append(content)
    return seen


def _norm(text: str) -> str:
    return re.sub(r"[\s ]+", "", text)


def find_suspicious_facts(document: str, sources: str) -> list[SuspiciousFact]:
    without_placeholders = _PLACEHOLDER.sub(" ", document)
    normalized_sources = _norm(sources)
    result: list[SuspiciousFact] = []
    seen: set[tuple[str, str]] = set()
    for kind, pattern in _PATTERNS:
        for m in pattern.finditer(without_placeholders):
            value = m.group(0)
            if kind == "url":
                value = value.rstrip(".,;:)")
            key = (kind, value)
            if key in seen or _norm(value) in normalized_sources:
                continue
            seen.add(key)
            result.append(SuspiciousFact(kind=kind, value=value))
    return result

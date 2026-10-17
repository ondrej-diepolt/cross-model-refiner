"""Deterministická kontrola faktů: placeholdery a údaje, které nejsou ve zdrojích."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

_PLACEHOLDER = re.compile(r"\[DOPLNIT(?::([^\]]*))?\]")

_VELKE = "A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ"
_MALE = "a-záčďéěíňóřšťúůýž"

# Pořadí je významné jen pro výstup; každý druh se hledá zvlášť.
_VZORY: list[tuple[str, re.Pattern[str]]] = [
    ("castka", re.compile(r"\d{1,3}(?:[  .]\d{3})*(?:,\d+)?\s?(?:Kč|CZK)")),
    ("ico", re.compile(r"\b\d{8}\b")),
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("telefon", re.compile(r"(?:\+420[  ]?)?\d{3}[  ]?\d{3}[  ]?\d{3}")),
    ("jmeno", re.compile(
        rf"\b(?:Ing|Mgr|Bc|JUDr|PhDr|RNDr|MUDr|doc|prof)\.\s+[{_VELKE}][{_MALE}]+"
        rf"(?:\s+[{_VELKE}][{_MALE}]+)?")),
    ("url", re.compile(r"https?://\S+")),
]


class PodezrelyUdaj(BaseModel):
    druh: Literal["castka", "ico", "email", "telefon", "jmeno", "url"]
    hodnota: str


def najdi_placeholdery(md: str) -> list[str]:
    videno: list[str] = []
    for m in _PLACEHOLDER.finditer(md):
        obsah = (m.group(1) or "").strip()
        if obsah not in videno:
            videno.append(obsah)
    return videno


def _norm(text: str) -> str:
    return re.sub(r"[\s ]+", "", text)


def podezrele_udaje(dokument: str, zdroje: str) -> list[PodezrelyUdaj]:
    bez_placeholderu = _PLACEHOLDER.sub(" ", dokument)
    zdroje_norm = _norm(zdroje)
    vysledek: list[PodezrelyUdaj] = []
    videno: set[tuple[str, str]] = set()
    for druh, vzor in _VZORY:
        for m in vzor.finditer(bez_placeholderu):
            hodnota = m.group(0)
            if druh == "url":
                hodnota = hodnota.rstrip(".,;:)")
            klic = (druh, hodnota)
            if klic in videno or _norm(hodnota) in zdroje_norm:
                continue
            videno.add(klic)
            vysledek.append(PodezrelyUdaj(druh=druh, hodnota=hodnota))
    return vysledek

"""Načítání vstupních dokumentů a podkladů a jejich převod na Markdown."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pypandoc

PODPOROVANE_PRIPONY = (".docx", ".md", ".txt")
NAZEV_SABLONY = "sablona.docx"


class ChybaVstupu(Exception):
    """Vstupní soubor nelze použít (např. je prázdný)."""


def _je_podporovany(cesta: Path) -> bool:
    n = cesta.name
    if not cesta.is_file() or n.startswith("~$") or n.startswith("."):
        return False
    if n.lower().endswith(".kriteria.yaml"):
        return False
    return cesta.suffix.lower() in PODPOROVANE_PRIPONY


def najdi_vstupy(slozka: Path) -> list[Path]:
    """Podporované vstupní soubory ve složce, seřazené podle názvu."""
    return sorted((p for p in Path(slozka).iterdir() if _je_podporovany(p)), key=lambda p: p.name)


def _nacti_text(cesta: Path) -> str:
    data = cesta.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1250")


def _jednotne_konce_radku(text: str) -> str:
    r"""Převede CRLF/CR na LF; jinak by zápis v textovém režimu na Windows vyrobil \r\r\n."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def nacti_jako_markdown(cesta: Path) -> str:
    """Text souboru jako Markdown (DOCX přes pandoc) s konci řádků LF."""
    cesta = Path(cesta)
    if cesta.suffix.lower() == ".docx":
        text = pypandoc.convert_file(str(cesta), "gfm")
    else:
        text = _nacti_text(cesta)
    if not text.strip():
        raise ChybaVstupu(f"Soubor {cesta.name} neobsahuje žádný text.")
    return _jednotne_konce_radku(text)


def nacti_podklady(slozka: Path) -> str:
    slozka = Path(slozka)
    if not slozka.is_dir():
        return ""
    casti = []
    for p in najdi_vstupy(slozka):
        if p.name.lower() == NAZEV_SABLONY:
            continue
        casti.append(f"## Podklad: {p.name}\n\n{nacti_jako_markdown(p).strip()}")
    return "\n\n".join(casti)


def slug(text: str, max_delka: int = 60) -> str:
    bez = unicodedata.normalize("NFKD", text)
    bez = "".join(c for c in bez if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", bez).strip("-")[:max_delka].strip("-")

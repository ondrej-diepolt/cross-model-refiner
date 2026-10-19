"""Read input documents and supporting materials as Markdown."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pypandoc

SUPPORTED_EXTENSIONS = (".docx", ".md", ".txt")
TEMPLATE_NAME = "sablona.docx"


class InputError(Exception):
    """An input file cannot be used, for example because it is empty."""


def _is_supported(path: Path) -> bool:
    n = path.name
    if not path.is_file() or n.startswith("~$") or n.startswith("."):
        return False
    if n.lower().endswith(".kriteria.yaml"):
        return False
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def find_inputs(directory: Path) -> list[Path]:
    """Supported input files in a directory, sorted by name."""
    return sorted((p for p in Path(directory).iterdir() if _is_supported(p)), key=lambda p: p.name)


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1250")


def _normalize_newlines(text: str) -> str:
    r"""Normalize CRLF/CR to LF to prevent Windows text-mode writes from producing \r\r\n."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_as_markdown(path: Path) -> str:
    """Return file text as Markdown (DOCX via pandoc), with LF newlines."""
    path = Path(path)
    if path.suffix.lower() == ".docx":
        text = pypandoc.convert_file(str(path), "gfm")
    else:
        text = _read_text(path)
    if not text.strip():
        raise InputError(f"Soubor {path.name} neobsahuje žádný text.")
    return _normalize_newlines(text)


def read_materials(directory: Path) -> str:
    directory = Path(directory)
    if not directory.is_dir():
        return ""
    parts = []
    for p in find_inputs(directory):
        if p.name.lower() == TEMPLATE_NAME:
            continue
        parts.append(f"## Podklad: {p.name}\n\n{read_as_markdown(p).strip()}")
    return "\n\n".join(parts)


def slug(text: str, max_length: int = 60) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    normalized = "".join(c for c in normalized if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")[:max_length].strip("-")

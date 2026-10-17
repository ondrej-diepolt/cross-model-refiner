"""Export Markdownu do DOCX přes pandoc, volitelně podle šablony."""
from __future__ import annotations

from pathlib import Path

import pypandoc


def exportuj_docx(md: str, cil: Path, sablona: Path | None) -> None:
    extra = [f"--reference-doc={sablona}"] if sablona else []
    pypandoc.convert_text(md, "docx", format="gfm", outputfile=str(cil), extra_args=extra)

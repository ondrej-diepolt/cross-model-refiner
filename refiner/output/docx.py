"""Export Markdown through pandoc, optionally using a reference template."""
from __future__ import annotations

from pathlib import Path

import pypandoc


def export_docx(md: str, destination: Path, template: Path | None) -> None:
    extra = [f"--reference-doc={template}"] if template else []
    pypandoc.convert_text(md, "docx", format="gfm", outputfile=str(destination), extra_args=extra)

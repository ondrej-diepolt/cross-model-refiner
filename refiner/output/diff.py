"""Colored diff of two document versions, calculated in code."""
from __future__ import annotations

import difflib


def diff_html(old: str, new: str, old_label: str, new_label: str) -> str:
    return difflib.HtmlDiff(wrapcolumn=100).make_file(
        old.splitlines(), new.splitlines(), old_label, new_label,
        context=True, numlines=3, charset="utf-8",
    )

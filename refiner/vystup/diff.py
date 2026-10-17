"""Barevný rozdíl dvou verzí textu (počítá kód, ne model)."""
from __future__ import annotations

import difflib


def diff_html(stary: str, novy: str, popis_stary: str, popis_novy: str) -> str:
    return difflib.HtmlDiff(wrapcolumn=100).make_file(
        stary.splitlines(), novy.splitlines(), popis_stary, popis_novy,
        context=True, numlines=3, charset="utf-8",
    )

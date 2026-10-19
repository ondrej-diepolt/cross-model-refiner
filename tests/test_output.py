import subprocess

import pypandoc

from refiner.scoring import format_score, calculate_score
from refiner.input import read_as_markdown
from refiner.output.diff import diff_html
from refiner.output.docx import export_docx
from refiner.output.markdown import evaluation_markdown, requirements_markdown, review_markdown
from refiner.data import Requirement
from tests.helpers import make_evaluation, make_criteria, make_settings, make_review

BS = chr(92)


def test_evaluation_markdown_contains_scores_and_criteria():
    k = make_criteria()
    h = make_evaluation(base=9.2, criteria=k)
    s = calculate_score(h, k, make_settings())
    md = evaluation_markdown(2, h, s, k)
    assert "Hodnocení 2" in md and "9,2" in md and "B3" in md and "Vnitřní konzistence" in md
    assert format_score(s.total) in md


def test_evaluation_markdown_includes_unmet_reasons():
    k = make_criteria()
    h = make_evaluation(base=3.0, criteria=k, facts=1)
    s = calculate_score(h, k, make_settings())
    md = evaluation_markdown(1, h, s, k)
    assert s.unmet_reasons and all(d in md for d in s.unmet_reasons)
    assert "Fakt 0" in md


def test_evaluation_markdown_escapes_pipes_and_newlines():
    k = make_criteria()
    h = make_evaluation(criteria=k)
    h.criteria[0].rationale = "a | b\nc"
    md = evaluation_markdown(1, h, calculate_score(h, k, make_settings()), k)
    assert "a " + BS + "| b c" in md
    row = next(r for r in md.splitlines() if "a " + BS + "| b c" in r)
    assert row.replace(BS + "|", "").count("|") == 6  # five columns


def test_review_markdown_counts_and_decisions():
    h = make_evaluation(suggestions=3)
    p = make_review(h)
    p.decisions[2].decision = 'rejected'
    p.decisions[2].rationale = "Odporuje zadání."
    md = review_markdown(1, h, p)
    assert "Přijato: 2" in md and "Odmítnuto: 1" in md and "Částečně: 0" in md
    assert "Odporuje zadání." in md and "Takto." in md and "Místo 1" in md


def test_requirements_markdown():
    md = requirements_markdown([Requirement(id="N1", text="Cena | celá", citation="cena")], ["pozor"])
    assert "N1" in md and "Cena " + BS + "| celá" in md and "pozor" in md


def test_diff_html_utf8_and_changes():
    html = diff_html("Cena: 100 Kč\n", "Cena: 120 Kč\n", "v1", "v2")
    assert "charset=utf-8" in html.lower() and "diff_chg" in html and "v2" in html  # intraline change: "1<span>2</span>0"


def test_diff_html_escapes_html():
    html = diff_html("<script>x</script>\n", "y\n", "a", "b")
    assert "<script>" not in html


def test_export_docx_with_table(tmp_path):
    export_docx("# Nabídka\n\n| A | B |\n|---|---|\n| 1 | 2 |\n", tmp_path / "x.docx", None)
    assert read_as_markdown(tmp_path / "x.docx").count("|") >= 6


def test_export_docx_with_template(tmp_path):
    template = tmp_path / "sablona.docx"
    data = subprocess.run([pypandoc.get_pandoc_path(), "--print-default-data-file", "reference.docx"],
                          capture_output=True, check=True).stdout
    template.write_bytes(data)
    export_docx("# Nabídka\n\nText.\n", tmp_path / "y.docx", template)
    assert "Nabídka" in read_as_markdown(tmp_path / "y.docx")

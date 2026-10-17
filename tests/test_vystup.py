import subprocess

import pypandoc

from refiner.skore import format_skore, spocitej
from refiner.vstup import nacti_jako_markdown
from refiner.vystup.diff import diff_html
from refiner.vystup.docx import exportuj_docx
from refiner.vystup.markdown import hodnoceni_md, nalezitosti_md, posouzeni_md
from refiner.data import Nalezitost
from tests.pomocne import hodnoceni, kriteria_test, nastaveni_test, posouzeni

BS = chr(92)


def test_hodnoceni_md_obsahuje_skore_a_duvody():
    k = kriteria_test()
    h = hodnoceni(zaklad=9.2, kriteria=k)
    s = spocitej(h, k, nastaveni_test())
    md = hodnoceni_md(2, h, s, k)
    assert "Hodnocení 2" in md and "9,2" in md and "B3" in md and "Vnitřní konzistence" in md
    assert format_skore(s.celkem) in md


def test_hodnoceni_md_ukazuje_duvody_nesplneni():
    k = kriteria_test()
    h = hodnoceni(zaklad=3.0, kriteria=k, fakta=1)
    s = spocitej(h, k, nastaveni_test())
    md = hodnoceni_md(1, h, s, k)
    assert s.duvody_nesplneni and all(d in md for d in s.duvody_nesplneni)
    assert "Fakt 0" in md


def test_hodnoceni_md_svislitko_v_textu_nerozbije_tabulku():
    k = kriteria_test()
    h = hodnoceni(kriteria=k)
    h.kriteria[0].zduvodneni = "a | b\nc"
    md = hodnoceni_md(1, h, spocitej(h, k, nastaveni_test()), k)
    assert "a " + BS + "| b c" in md
    radek = next(r for r in md.splitlines() if "a " + BS + "| b c" in r)
    assert radek.replace(BS + "|", "").count("|") == 6  # 5 sloupců


def test_posouzeni_md_pocty_a_rozhodnuti():
    h = hodnoceni(navrhy=3)
    p = posouzeni(h)
    p.rozhodnuti[2].rozhodnuti = "odmitnuto"
    p.rozhodnuti[2].zduvodneni = "Odporuje zadání."
    md = posouzeni_md(1, h, p)
    assert "Přijato: 2" in md and "Odmítnuto: 1" in md and "Částečně: 0" in md
    assert "Odporuje zadání." in md and "Takto." in md and "Místo 1" in md


def test_nalezitosti_md():
    md = nalezitosti_md([Nalezitost(id="N1", text="Cena | celá", citace="cena")], ["pozor"])
    assert "N1" in md and "Cena " + BS + "| celá" in md and "pozor" in md


def test_diff_html_utf8_a_zmena():
    html = diff_html("Cena: 100 Kč\n", "Cena: 120 Kč\n", "v1", "v2")
    assert "charset=utf-8" in html.lower() and "diff_chg" in html and "v2" in html  # změna je intraline: "1<span>2</span>0"


def test_diff_html_escapuje_html():
    html = diff_html("<script>x</script>\n", "y\n", "a", "b")
    assert "<script>" not in html


def test_exportuj_docx_s_tabulkou(tmp_path):
    exportuj_docx("# Nabídka\n\n| A | B |\n|---|---|\n| 1 | 2 |\n", tmp_path / "x.docx", None)
    assert nacti_jako_markdown(tmp_path / "x.docx").count("|") >= 6


def test_exportuj_docx_se_sablonou(tmp_path):
    sablona = tmp_path / "sablona.docx"
    data = subprocess.run([pypandoc.get_pandoc_path(), "--print-default-data-file", "reference.docx"],
                          capture_output=True, check=True).stdout
    sablona.write_bytes(data)
    exportuj_docx("# Nabídka\n\nText.\n", tmp_path / "y.docx", sablona)
    assert "Nabídka" in nacti_jako_markdown(tmp_path / "y.docx")

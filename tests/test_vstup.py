"""Testy načítání vstupů a podkladů."""
import pypandoc
import pytest

from refiner.vstup import ChybaVstupu, najdi_vstupy, nacti_jako_markdown, nacti_podklady, slug


def test_najdi_vstupy_ignoruje_docasne_soubory_wordu(tmp_path):
    for n in ["Národní rozvojová banka.docx", "~$rodní rozvojová banka.docx", ".skryty.md",
              "a.kriteria.yaml", "obrazek.png", "b.md"]:
        (tmp_path / n).write_bytes(b"x")
    assert [p.name for p in najdi_vstupy(tmp_path)] == ["Národní rozvojová banka.docx", "b.md"]


def test_docx_s_diakritikou_v_nazvu(tmp_path):
    zdroj = "# Poptávka\n\n- Nabídka proto musí obsahovat cenu\n- Druhá položka\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
    cesta = tmp_path / "Národní rozvojová banka.docx"
    pypandoc.convert_text(zdroj, "docx", format="md", outputfile=str(cesta))
    md = nacti_jako_markdown(cesta)
    assert "Nabídka proto musí obsahovat" in md and "|" in md and "- " in md


def test_txt_v_cp1250(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes("Poptávka – žluťoučký kůň".encode("cp1250"))
    assert nacti_jako_markdown(p) == "Poptávka – žluťoučký kůň"


def test_md_s_bom(tmp_path):
    p = tmp_path / "a.md"
    p.write_bytes("﻿Ahoj".encode("utf-8"))
    assert nacti_jako_markdown(p) == "Ahoj"


def test_konce_radku_crlf_a_cr_se_sjednoti(tmp_path):
    r"""Jinak by zápis v textovém režimu na Windows vyrobil \r\r\n (dvojité řádky)."""
    p = tmp_path / "a.md"
    p.write_bytes(b"# Popt\r\n\r\nText.\rDalsi\r\n")
    assert nacti_jako_markdown(p) == "# Popt\n\nText.\nDalsi\n"


def test_podklady_crlf(tmp_path):
    (tmp_path / "profil.md").write_bytes(b"Firma\r\nIC\r\n")
    out = nacti_podklady(tmp_path)
    assert "Firma\nIC" in out and "\r" not in out


def test_prazdny_vstup(tmp_path):
    p = tmp_path / "prazdny.md"
    p.write_text("   \n", encoding="utf-8")
    with pytest.raises(ChybaVstupu) as e:
        nacti_jako_markdown(p)
    assert "prazdny.md" in str(e.value)


def test_podklady_spoji_soubory_bez_sablony(tmp_path):
    (tmp_path / "profil_firmy.md").write_text("Sazba 15 000 Kč", encoding="utf-8")
    pypandoc.convert_text("Šablona", "docx", format="md", outputfile=str(tmp_path / "sablona.docx"))
    out = nacti_podklady(tmp_path)
    assert "## Podklad: profil_firmy.md" in out and "Sazba 15 000 Kč" in out
    assert "Šablona" not in out and "sablona" not in out


def test_podklady_chybi(tmp_path):
    assert nacti_podklady(tmp_path / "neni") == ""


def test_slug():
    assert slug("Národní rozvojová banka") == "narodni-rozvojova-banka"
    assert len(slug("a" * 100)) <= 60

"""Tests for reading input documents and materials."""
import pypandoc
import pytest

from refiner.input import InputError, find_inputs, read_as_markdown, read_materials, slug


def test_find_inputs_ignores_temporary_word_files(tmp_path):
    for n in ["Národní rozvojová banka.docx", "~$rodní rozvojová banka.docx", ".skryty.md",
              "a.kriteria.yaml", "obrazek.png", "b.md"]:
        (tmp_path / n).write_bytes(b"x")
    assert [p.name for p in find_inputs(tmp_path)] == ["Národní rozvojová banka.docx", "b.md"]


def test_docx_with_accented_filename(tmp_path):
    source = "# Poptávka\n\n- Nabídka proto musí obsahovat cenu\n- Druhá položka\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
    path = tmp_path / "Národní rozvojová banka.docx"
    pypandoc.convert_text(source, "docx", format="md", outputfile=str(path))
    md = read_as_markdown(path)
    assert "Nabídka proto musí obsahovat" in md and "|" in md and "- " in md


def test_txt_in_cp1250(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes("Poptávka – žluťoučký kůň".encode("cp1250"))
    assert read_as_markdown(p) == "Poptávka – žluťoučký kůň"


def test_md_with_bom(tmp_path):
    p = tmp_path / "a.md"
    p.write_bytes("﻿Ahoj".encode("utf-8"))
    assert read_as_markdown(p) == "Ahoj"


def test_crlf_and_cr_newlines_are_normalized(tmp_path):
    r"""Windows text-mode writes would otherwise produce \r\r\n (duplicate lines)."""
    p = tmp_path / "a.md"
    p.write_bytes(b"# Popt\r\n\r\nText.\rDalsi\r\n")
    assert read_as_markdown(p) == "# Popt\n\nText.\nDalsi\n"


def test_materials_crlf(tmp_path):
    (tmp_path / "profil.md").write_bytes(b"Firma\r\nIC\r\n")
    out = read_materials(tmp_path)
    assert "Firma\nIC" in out and "\r" not in out


def test_empty_input(tmp_path):
    p = tmp_path / "prazdny.md"
    p.write_text("   \n", encoding="utf-8")
    with pytest.raises(InputError) as e:
        read_as_markdown(p)
    assert "prazdny.md" in str(e.value)


def test_materials_combines_files_without_template(tmp_path):
    (tmp_path / "profil_firmy.md").write_text("Sazba 15 000 Kč", encoding="utf-8")
    pypandoc.convert_text("Šablona", "docx", format="md", outputfile=str(tmp_path / "sablona.docx"))
    out = read_materials(tmp_path)
    assert "## Podklad: profil_firmy.md" in out and "Sazba 15 000 Kč" in out
    assert "Šablona" not in out and "sablona" not in out


def test_missing_materials(tmp_path):
    assert read_materials(tmp_path / "neni") == ""


def test_slug():
    assert slug("Národní rozvojová banka") == "narodni-rozvojova-banka"
    assert len(slug("a" * 100)) <= 60


def test_english_materials_precede_legacy_without_combining(tmp_path):
    from refiner.input import resolve_materials_directory

    legacy = tmp_path / "podklady"
    legacy.mkdir()
    (legacy / "profil_firmy.md").write_text("LEGACY_ONLY", encoding="utf-8")
    assert resolve_materials_directory(tmp_path) == legacy
    current = tmp_path / "materials"
    current.mkdir()
    (current / "company_profile.md").write_text("ENGLISH_ONLY", encoding="utf-8")
    assert resolve_materials_directory(tmp_path) == current
    text = read_materials(resolve_materials_directory(tmp_path))
    assert "ENGLISH_ONLY" in text and "LEGACY_ONLY" not in text
    assert (legacy / "profil_firmy.md").read_text(encoding="utf-8") == "LEGACY_ONLY"


def test_missing_materials_resolves_to_new_directory(tmp_path):
    from refiner.input import resolve_materials_directory

    assert resolve_materials_directory(tmp_path) == tmp_path / "materials"


def test_template_precedence_and_exclusion_from_model_text(tmp_path):
    from refiner.input import find_template

    (tmp_path / "company_profile.md").write_text("Firma Alfa", encoding="utf-8")
    legacy = tmp_path / "sablona.docx"
    current = tmp_path / "template.docx"
    assert find_template(tmp_path) is None
    legacy.write_bytes(b"legacy template must never be read as model input")
    assert find_template(tmp_path) == legacy
    current.write_bytes(b"English template must never be read as model input")
    assert find_template(tmp_path) == current
    assert read_materials(tmp_path) == "## Podklad: company_profile.md\n\nFirma Alfa"

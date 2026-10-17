import shutil
from datetime import datetime
from pathlib import Path

import pytest

import refiner.aplikace as aplikace
from refiner.aplikace import dokonci, najdi_posledni_beh, obnov_beh, zahaj_beh
from refiner.beh import Beh
from refiner.modely.chyby import ChybaModelu
from refiner.modely.falesne import FalesnyModel
from refiner.vstup import ChybaVstupu
from tests.pomocne import POPTAVKA_TEST, hodnoceni, odpovedi_skriptu, skript

T = datetime(2026, 10, 17, 9, 0)


@pytest.fixture
def koren(tmp_path, koren_repa) -> Path:
    """Kořen aplikace v tmp: kopie nastaveni.yaml, profily/, prompty/ a input/poptavka.md."""
    k = tmp_path / "app"
    k.mkdir()
    shutil.copy(koren_repa / "nastaveni.yaml", k / "nastaveni.yaml")
    shutil.copytree(koren_repa / "profily", k / "profily")
    shutil.copytree(koren_repa / "prompty", k / "prompty")
    (k / "input").mkdir()
    (k / "input" / "poptavka.md").write_text(POPTAVKA_TEST, encoding="utf-8")
    return k


def _zahaj(koren: Path, ted: datetime = T):
    return zahaj_beh(koren, koren / "input" / "poptavka.md", "nabidka", ted)


# ---------------------------------------------------------------- zahájení a obnovení

def test_zahaj_beh_zkopiruje_konfiguraci_a_vstup(koren):
    (koren / "podklady").mkdir()
    (koren / "podklady" / "profil_firmy.md").write_text("Firma Alfa s.r.o.", encoding="utf-8")
    (koren / "input" / "poptavka.kriteria.yaml").write_text("vahy: {B1: 2}\n", encoding="utf-8")

    beh, z = _zahaj(koren)

    assert beh.slozka.parent == koren / "output"
    assert (beh.slozka / "01_poptavka.md").exists()
    assert (beh.slozka / "01_poptavka.md").read_text(encoding="utf-8") == POPTAVKA_TEST
    konf = beh.slozka / "data" / "konfigurace"
    assert (konf / "prompty" / "navrh.md").exists()
    assert (konf / "nastaveni.yaml").exists()
    assert (konf / "profil.yaml").read_text(encoding="utf-8") == \
        (koren / "profily" / "nabidka.yaml").read_text(encoding="utf-8")
    assert (konf / "kriteria.yaml").exists()
    assert z.prompty == beh.slozka / "data" / "konfigurace" / "prompty"
    assert z.poptavka == POPTAVKA_TEST
    assert "Firma Alfa s.r.o." in z.podklady
    assert "Firma Alfa s.r.o." in (beh.slozka / "data" / "podklady.md").read_text(encoding="utf-8")
    assert z.konfigurace.profil_nazev == "nabidka"
    assert {k.id: k.vaha for k in z.konfigurace.kriteria_profilu}["B1"] == 2
    assert beh.stav.profil == "nabidka" and beh.stav.vstup == "poptavka.md"


def test_zahaj_beh_bez_kriterii_a_podkladu(koren):
    beh, z = _zahaj(koren)
    assert not (beh.slozka / "data" / "konfigurace" / "kriteria.yaml").exists()
    assert z.podklady == ""
    assert (beh.slozka / "data" / "podklady.md").read_text(encoding="utf-8") == ""


def test_zahaj_beh_crlf_vstup_nezdvoji_radky(koren):
    (koren / "input" / "poptavka.md").write_bytes(b"# Popt\r\n\r\nText.\r\n")
    (koren / "podklady").mkdir()
    (koren / "podklady" / "profil.md").write_bytes(b"Firma\r\nIC\r\n")
    beh, z = _zahaj(koren)
    assert z.poptavka == "# Popt\n\nText.\n"
    assert beh.text("poptavka") == "# Popt\n\nText.\n"
    assert "Firma\nIC" in z.podklady and "\r" not in z.podklady


def test_obnoveni_pouzije_kopii_konfigurace(koren):
    beh, _ = _zahaj(koren)
    nastaveni = koren / "nastaveni.yaml"
    nastaveni.write_text(nastaveni.read_text(encoding="utf-8").replace("max_revizi: 3", "max_revizi: 1"),
                         encoding="utf-8")
    (koren / "prompty" / "navrh.md").write_text("ZMĚNĚNO", encoding="utf-8")

    beh2, z2 = obnov_beh(beh.slozka)

    assert beh2.slozka == beh.slozka
    assert z2.konfigurace.nastaveni.smycka.max_revizi == 3
    assert z2.prompty == beh.slozka / "data" / "konfigurace" / "prompty"
    assert (z2.prompty / "navrh.md").read_text(encoding="utf-8") != "ZMĚNĚNO"
    assert z2.konfigurace.profil_nazev == "nabidka"
    assert z2.poptavka == POPTAVKA_TEST
    # obnovení nepřepisuje existující kroky
    assert list(beh2.stav.kroky) == ["poptavka"] and beh2.stav.kroky["poptavka"].cislo == 1


def test_obnoveni_dokonceneho_behu_odmitne(koren):
    beh, z = _zahaj(koren)
    assert dokonci(beh, z, *skript([9.5]), hlaseni=lambda _: None, sablona=None) == 0
    with pytest.raises(ChybaVstupu, match="je už dokončený"):
        obnov_beh(beh.slozka)


def test_obnoveni_slozky_ktera_neni_beh(tmp_path):
    with pytest.raises(ChybaVstupu):
        obnov_beh(tmp_path)


# ---------------------------------------------------------------- dokončení

def test_dokonci_uspech(koren):
    beh, z = _zahaj(koren)
    out: list[str] = []
    assert dokonci(beh, z, *skript([9.5]), hlaseni=out.append, sablona=None) == 0
    assert (beh.slozka / "FINALNI_nabidka.docx").exists() and (beh.slozka / "prehled.html").exists()
    assert (beh.slozka / "FINALNI_nabidka.md").read_text(encoding="utf-8") == \
        (beh.slozka / "03_navrh_v1.md").read_text(encoding="utf-8")
    st = Beh.otevri(beh.slozka).stav
    assert st.stav == "dokoncen" and st.duvod_ukonceni == "cil_splnen" and st.finalni_verze == 1
    assert st.chyba is None
    assert any(str(beh.slozka / "prehled.html") in r for r in out)


def test_chyba_api_ulozi_rozpracovany_beh(koren):
    beh, z = _zahaj(koren)
    pisatel, _ = skript([9.5])
    hodnotitel = FalesnyModel({"hodnoceni_1": [ChybaModelu("kredit", "OpenAI")]}, nazev="gpt-falesny")
    out: list[str] = []
    assert dokonci(beh, z, pisatel, hodnotitel, hlaseni=out.append, sablona=None) == 1
    st = Beh.otevri(beh.slozka).stav
    assert st.stav == "prerusen" and "kredit" in st.chyba and (beh.slozka / "03_navrh_v1.md").exists()
    vypis = "\n".join(out)
    assert "pokracovat.bat" in vypis and (beh.slozka / "prehled.html").exists()
    assert "Došel kredit u OpenAI" in vypis and str(beh.slozka) in vypis
    assert "Běh byl přerušen" in (beh.slozka / "prehled.html").read_text(encoding="utf-8")
    assert "ChybaModelu" in (beh.slozka / "data" / "beh.log").read_text(encoding="utf-8")


def test_surova_odpoved_se_ulozi(koren):
    beh, z = _zahaj(koren)
    pisatel, _ = skript([9.5])
    # nevalidní výstup kroky jednou opraví; až druhé selhání ukončí krok
    chyba = ChybaModelu("nevalidni_vystup", "OpenAI", surova_odpoved="{rozbite")
    hodnotitel = FalesnyModel({"hodnoceni_1": [chyba, chyba]}, nazev="gpt-falesny")
    assert dokonci(beh, z, pisatel, hodnotitel, hlaseni=lambda _: None, sablona=None) == 1
    soubory = list((beh.slozka / "data").glob("surova_odpoved_*.txt"))
    assert len(soubory) == 1
    assert soubory[0].read_text(encoding="utf-8") == "{rozbite"


def test_spotreba_neplatne_odpovedi_se_ulozi(koren):
    # Hodnotitel 2× odpoví (spotřeba vznikne), ale skóre 9,8 neprojde kontrolou → ChybaModelu.
    beh, z = _zahaj(koren)
    pisatel, _ = skript([9.5])
    spatne = hodnoceni(8.0, prepsat={"B1": 9.8})
    hodnotitel = FalesnyModel({"hodnoceni_1": [spatne, spatne]}, nazev="gpt-falesny")
    assert dokonci(beh, z, pisatel, hodnotitel, hlaseni=lambda _: None, sablona=None) == 1
    st = Beh.otevri(beh.slozka).stav
    assert [s.krok for s in st.spotreba if s.model == "gpt-falesny"] == ["hodnoceni_1", "hodnoceni_1"]
    assert len((list((beh.slozka / "data").glob("surova_odpoved_*.txt")))) == 1


def test_ctrl_c_ulozi_prerusen_beh(koren):
    beh, z = _zahaj(koren)
    odp_p, odp_h = odpovedi_skriptu([9.5])
    odp_p["navrh_1"] = [KeyboardInterrupt(), *odp_p["navrh_1"]]
    pisatel = FalesnyModel(odp_p, nazev="claude-falesny")
    hodnotitel = FalesnyModel(odp_h, nazev="gpt-falesny")
    out: list[str] = []

    assert dokonci(beh, z, pisatel, hodnotitel, hlaseni=out.append, sablona=None) == 1
    st = Beh.otevri(beh.slozka).stav
    assert st.stav == "prerusen" and "Ctrl+C" in st.chyba
    assert "pokracovat.bat" in "\n".join(out)
    assert (beh.slozka / "02_nalezitosti.md").exists() and not (beh.slozka / "03_navrh_v1.md").exists()

    beh2, z2 = obnov_beh(beh.slozka)
    assert dokonci(beh2, z2, pisatel, hodnotitel, hlaseni=out.append, sablona=None) == 0
    st = Beh.otevri(beh.slozka).stav
    assert st.stav == "dokoncen" and st.chyba is None
    assert (beh.slozka / "03_navrh_v1.md").exists() and (beh.slozka / "FINALNI_nabidka.docx").exists()
    assert [k for k, v in st.kroky.items() if v.cislo == 2] == ["nalezitosti"]


def test_neocekavana_vyjimka(koren):
    beh, z = _zahaj(koren)
    pisatel = FalesnyModel({"nalezitosti": [ZeroDivisionError("deleni nulou")]}, nazev="claude-falesny")
    _, hodnotitel = skript([9.5])
    out: list[str] = []
    assert dokonci(beh, z, pisatel, hodnotitel, hlaseni=out.append, sablona=None) == 1
    st = Beh.otevri(beh.slozka).stav
    assert st.stav == "prerusen" and "Neočekávaná chyba" in st.chyba
    assert "Neočekávaná chyba" in "\n".join(out)
    log = (beh.slozka / "data" / "beh.log").read_text(encoding="utf-8")
    assert "Traceback" in log and "ZeroDivisionError" in log


def test_selhani_prehledu_neprebije_puvodni_chybu(koren, monkeypatch):
    def rozbity(*_a, **_k):
        raise RuntimeError("šablona přehledu je rozbitá")

    monkeypatch.setattr(aplikace, "vytvor_prehled", rozbity)
    beh, z = _zahaj(koren)
    pisatel, _ = skript([9.5])
    hodnotitel = FalesnyModel({"hodnoceni_1": [ChybaModelu("kredit", "OpenAI")]}, nazev="gpt-falesny")
    out: list[str] = []
    assert dokonci(beh, z, pisatel, hodnotitel, hlaseni=out.append, sablona=None) == 1
    st = Beh.otevri(beh.slozka).stav
    assert st.stav == "prerusen" and "kredit" in st.chyba
    assert "Došel kredit" in "\n".join(out)
    assert "šablona přehledu je rozbitá" in (beh.slozka / "data" / "beh.log").read_text(encoding="utf-8")


def test_selhani_docx_exportu_je_varovani(koren, monkeypatch):
    def rozbity(*_a, **_k):
        raise OSError("pandoc nenalezen")

    monkeypatch.setattr(aplikace, "exportuj_docx", rozbity)
    beh, z = _zahaj(koren)
    assert dokonci(beh, z, *skript([9.5]), hlaseni=lambda _: None, sablona=None) == 0
    st = Beh.otevri(beh.slozka).stav
    assert st.stav == "dokoncen"
    assert any("DOCX" in v and "pandoc nenalezen" in v for v in st.varovani)
    assert (beh.slozka / "FINALNI_nabidka.md").exists()
    assert not (beh.slozka / "FINALNI_nabidka.docx").exists()


def test_log_handler_se_po_dokonceni_odpoji(koren):
    import logging

    beh, z = _zahaj(koren)
    pred = list(logging.getLogger("refiner").handlers)
    dokonci(beh, z, *skript([9.5]), hlaseni=lambda _: None, sablona=None)
    assert logging.getLogger("refiner").handlers == pred
    # soubor je uzavřený – jde smazat i na Windows
    (beh.slozka / "data" / "beh.log").unlink()


# ---------------------------------------------------------------- hledání posledního běhu

def test_najdi_posledni_preruseny(koren):
    output = koren / "output"
    assert najdi_posledni_beh(output, {"prerusen", "bezi"}) is None

    stary, _ = _zahaj(koren, datetime(2026, 10, 17, 8, 0))
    stary.ukonci("prerusen", chyba="x")
    novy, _ = _zahaj(koren, datetime(2026, 10, 17, 10, 0))
    novy.ukonci("prerusen", chyba="x")
    hotovy, _ = _zahaj(koren, datetime(2026, 10, 17, 11, 0))
    hotovy.ukonci("dokoncen", "cil_splnen", finalni_verze=1)
    (output / "nahodna_slozka").mkdir()
    (output / "rozbity").mkdir()
    (output / "rozbity" / "data").mkdir()
    (output / "rozbity" / "data" / "beh.json").write_text("{", encoding="utf-8")

    assert najdi_posledni_beh(output, {"prerusen", "bezi"}) == novy.slozka
    assert najdi_posledni_beh(output, {"dokoncen"}) == hotovy.slozka
    assert najdi_posledni_beh(output, {"bezi"}) is None

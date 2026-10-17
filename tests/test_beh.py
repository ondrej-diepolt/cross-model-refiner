import json
from datetime import datetime

from refiner.beh import Beh
from refiner.data import Hodnoceni, Spotreba, VysledekSkore, VystupNalezitosti

T = datetime(2026, 10, 17, 14, 32)


def test_nazev_slozky_bez_diakritiky(tmp_path):
    b = Beh.novy(tmp_path, "Národní rozvojová banka", "nabidka", T)
    assert b.slozka.name == "2026-10-17_1432_narodni-rozvojova-banka" and (b.slozka / "data").is_dir()


def test_kolize_prida_priponu(tmp_path):
    b1 = Beh.novy(tmp_path, "Banka.md", "nabidka", T)
    b2 = Beh.novy(tmp_path, "Banka.md", "nabidka", T)
    b3 = Beh.novy(tmp_path, "Banka.md", "nabidka", T)
    assert b1.slozka.name == "2026-10-17_1432_banka"
    assert b2.slozka.name == "2026-10-17_1432_banka_2"
    assert b3.slozka.name == "2026-10-17_1432_banka_3"


def test_cislovani_v_poradi_vzniku(tmp_path):
    b = Beh.novy(tmp_path, "x.md", "nabidka", T)
    b.zapis("poptavka", "poptavka.md", "x")
    b.zapis("nalezitosti", "nalezitosti.md", "y", data=VystupNalezitosti(nalezitosti=[]))
    p = b.zapis("navrh_1", "navrh_v1.md", "z")
    d = b.zapis_k("navrh_1", "navrh_v1_zmeny.html", "<p>")
    assert p.name == "03_navrh_v1.md" and d.name == "03_navrh_v1_zmeny.html"
    assert (b.slozka / "data" / "02_nalezitosti.json").exists()
    assert b.text("navrh_1") == "z"


def test_rezim_nanecisto_se_ulozi(tmp_path):
    assert Beh.otevri(Beh.novy(tmp_path, "a.md", "nabidka", T, nanecisto=True).slozka).stav.nanecisto
    assert not Beh.otevri(Beh.novy(tmp_path, "b.md", "nabidka", T).slozka).stav.nanecisto


def test_starsi_beh_bez_rezimu_se_nacte_jako_ostry(tmp_path):
    b = Beh.novy(tmp_path, "x.md", "nabidka", T)
    soubor = b.slozka / "data" / "beh.json"
    stav = json.loads(soubor.read_text(encoding="utf-8"))
    del stav["nanecisto"]
    soubor.write_text(json.dumps(stav), encoding="utf-8")
    assert Beh.otevri(b.slozka).stav.nanecisto is False


def test_otevri_obnovi_stav_a_data(tmp_path):
    b = Beh.novy(tmp_path, "x.md", "nabidka", T)
    h = Hodnoceni(kriteria=[], vymyslena_fakta=[], tvrzeni_k_overeni=[], navrhy=[], celkovy_komentar="ok")
    b.zapis("hodnoceni_1", "hodnoceni_v1.md", "text", data=h)
    b2 = Beh.otevri(b.slozka)
    assert b2.hotovo("hodnoceni_1") and not b2.hotovo("jine")
    assert b2.data("hodnoceni_1", Hodnoceni) == h
    assert b2.text("hodnoceni_1") == "text"
    assert b2.stav.vstup == "x.md" and b2.stav.vytvoreno == T


def test_stav_se_uklada_po_kazdem_zapisu(tmp_path):
    b = Beh.novy(tmp_path, "x.md", "nabidka", T)
    b.zapis("poptavka", "poptavka.md", "x")
    stav = json.loads((b.slozka / "data" / "beh.json").read_text(encoding="utf-8"))
    assert "poptavka" in stav["kroky"]


def test_atomicky_zapis_nenecha_tmp(tmp_path):
    b = Beh.novy(tmp_path, "x.md", "nabidka", T)
    b.uloz()
    assert (b.slozka / "data" / "beh.json").exists()
    assert not (b.slozka / "data" / "beh.json.tmp").exists()


def test_ukonci_prerusen(tmp_path):
    b = Beh.novy(tmp_path, "x.md", "nabidka", T)
    b.ukonci("prerusen", duvod="chyba", chyba="boom")
    b2 = Beh.otevri(b.slozka)
    assert b2.stav.stav == "prerusen" and b2.stav.chyba == "boom" and b2.stav.ukonceno is not None


def test_spotreba_a_skore_se_prictou(tmp_path):
    b = Beh.novy(tmp_path, "x.md", "nabidka", T)
    s = Spotreba(krok="a", model="m", vstup=1, vystup=2)
    b.pridej_spotrebu([s])
    b.pridej_spotrebu([s])
    b.pridej_varovani("pozor")
    v = VysledekSkore(a=1, b=1, c=1, celkem=1, cil_splnen=True, duvody_nesplneni=[])
    b.uloz_skore(1, v)
    b2 = Beh.otevri(b.slozka)
    assert len(b2.stav.spotreba) == 2 and b2.stav.varovani == ["pozor"]
    assert b2.stav.skore["1"] == v


def test_zapis_pevny(tmp_path):
    b = Beh.novy(tmp_path, "x.md", "nabidka", T)
    p = b.zapis_pevny("prehled.html", "<p>")
    q = b.zapis_pevny("data/konfigurace/a.bin", b"\x00")
    assert p.read_text(encoding="utf-8") == "<p>" and q.read_bytes() == b"\x00"

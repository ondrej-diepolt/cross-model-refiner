import pytest

from refiner.beh import Beh
from refiner.modely.chyby import ChybaModelu
from refiner.modely.falesne import FalesnyModel
from refiner.smycka import spust_smycku
from tests.pomocne import (
    beh_test,
    hodnoceni,
    odpovedi_skriptu,
    posouzeni,
    skript,
    text_navrhu,
)


def _kroky(model: FalesnyModel) -> list[str]:
    return [k for k, *_ in model.volani]


def _ticho(_: str) -> None:
    pass


def test_cil_splnen_v_prvnim_hodnoceni(tmp_path, zdroje):
    beh = beh_test(tmp_path, zdroje)
    v = spust_smycku(beh, zdroje, *skript([9.5]), hlaseni=_ticho)
    assert v.duvod == "cil_splnen" and v.finalni_verze == 1
    assert [p.name for p in sorted(beh.slozka.glob("0*"))] == [
        "01_poptavka.md", "02_nalezitosti.md", "03_navrh_v1.md", "04_hodnoceni_1.md"]
    assert list(v.skore) == [1] and v.skore[1].cil_splnen and v.skore[1].celkem == 9.6
    assert beh.stav.skore["1"].celkem == v.skore[1].celkem


def test_cil_splnen_ve_druhem(tmp_path, zdroje):
    beh = beh_test(tmp_path, zdroje)
    pis, hod = skript([7.0, 9.5])
    v = spust_smycku(beh, zdroje, pis, hod, hlaseni=_ticho)
    assert v.duvod == "cil_splnen" and v.finalni_verze == 2
    assert _kroky(hod) == ["hodnoceni_1", "hodnoceni_2"]
    assert _kroky(pis) == ["nalezitosti", "navrh_1", "posouzeni_1", "navrh_2"]
    assert beh.text("navrh_2") == text_navrhu(2)


def test_tri_revize_a_zaverecne_hodnoceni(tmp_path, zdroje):
    beh = beh_test(tmp_path, zdroje)
    pis, hod = skript([7.0, 8.0, 8.5, 9.0])
    v = spust_smycku(beh, zdroje, pis, hod, hlaseni=_ticho)
    assert v.duvod == "limit_revizi" and len(v.skore) == 4
    assert v.finalni_verze == 4
    assert _kroky(hod) == ["hodnoceni_1", "hodnoceni_2", "hodnoceni_3", "hodnoceni_4"]
    assert sum(1 for k in _kroky(pis) if k.startswith("navrh_")) == 4   # v1 + 3 revize
    assert "posouzeni_4" not in _kroky(pis)
    assert (beh.slozka / "06_navrh_v2_zmeny.html").exists()
    assert set(beh.stav.skore) == {"1", "2", "3", "4"}


def test_nic_neprijato_ukonci_bez_dalsiho_hodnoceni(tmp_path, zdroje):
    beh = beh_test(tmp_path, zdroje)
    pis, hod = skript([7.0, 9.5], rozhodnuti="odmitnuto")
    v = spust_smycku(beh, zdroje, pis, hod, hlaseni=_ticho)
    assert v.duvod == "zadna_zmena" and v.finalni_verze == 1
    assert _kroky(hod) == ["hodnoceni_1"]
    assert "navrh_2" not in _kroky(pis)
    assert (beh.slozka / "05_posouzeni_1.md").exists()


def test_pokles_skore_vybere_drivejsi_verzi(tmp_path, zdroje):
    beh = beh_test(tmp_path, zdroje)
    v = spust_smycku(beh, zdroje, *skript([7.0, 9.0, 8.0, 8.5]), hlaseni=_ticho)
    assert v.duvod == "limit_revizi"
    assert v.finalni_verze == 2


def test_splneny_cil_ma_prednost_pred_vyssim_zablokovanym_skore(tmp_path, zdroje):
    """v2 má vyšší skóre, ale cíl blokuje náležitost pod minimem; v3 cíl splní → finální v3."""
    beh = beh_test(tmp_path, zdroje)
    pis, hod = odpovedi_skriptu([7.0, 10.0, 9.5])
    h2 = hodnoceni(10.0, {"N1": 7.5})
    hod["hodnoceni_2"] = [h2]
    pis["posouzeni_2"] = [posouzeni(h2)]
    hod["hodnoceni_3"] = [hodnoceni(9.5, {"B1": 9.0})]
    v = spust_smycku(beh, zdroje, FalesnyModel(pis, nazev="claude-falesny"),
                     FalesnyModel(hod, nazev="gpt-falesny"), hlaseni=_ticho)
    assert not v.skore[2].cil_splnen and v.skore[3].cil_splnen
    assert v.skore[2].celkem > v.skore[3].celkem
    assert v.duvod == "cil_splnen" and v.finalni_verze == 3


def _odpovedi_se_smisenym_posouzenim(skore: list[float]):
    """Kolo 1: návrh V1 přijat částečně, V2 odmítnut (s rozpoznatelným textem)."""
    pis, hod = odpovedi_skriptu(skore)
    h1 = hodnoceni(skore[0])
    h1 = h1.model_copy(update={"navrhy": [
        h1.navrhy[0].model_copy(update={"navrh": "Doplnit tabulku rizik."}),
        h1.navrhy[1].model_copy(update={"navrh": "Přidat neexistující referenci ODMITNUTO-XYZ."}),
    ]})
    p1 = posouzeni(h1, "castecne")
    p1.rozhodnuti[1] = p1.rozhodnuti[1].model_copy(
        update={"rozhodnuti": "odmitnuto", "zduvodneni": "Reference není ve zdrojích."})
    hod["hodnoceni_1"] = [h1]
    pis["posouzeni_1"] = [p1]
    return pis, hod


def test_odmitnute_navrhy_jdou_do_dalsiho_hodnoceni(tmp_path, zdroje):
    beh = beh_test(tmp_path, zdroje)
    pis_o, hod_o = _odpovedi_se_smisenym_posouzenim([7.0, 9.5])
    pis, hod = FalesnyModel(pis_o), FalesnyModel(hod_o, nazev="gpt-falesny")
    v = spust_smycku(beh, zdroje, pis, hod, hlaseni=_ticho)
    assert v.duvod == "cil_splnen"
    instrukce = {k: i for k, i, _ in hod.volani}
    assert "ODMITNUTO-XYZ" in instrukce["hodnoceni_2"]
    assert "Reference není ve zdrojích." in instrukce["hodnoceni_2"]
    assert "Doplnit tabulku rizik." not in instrukce["hodnoceni_2"]   # částečně přijatý není odmítnutý
    assert "ODMITNUTO-XYZ" not in instrukce["hodnoceni_1"]


def test_obnoveni_nevola_hotove_kroky(tmp_path, zdroje):
    beh = beh_test(tmp_path, zdroje)
    pis_o, hod_o = odpovedi_skriptu([7.0, 8.0, 9.5])
    hod_o["hodnoceni_2"] = [ChybaModelu("pretizeni", "OpenAI")]
    with pytest.raises(ChybaModelu):
        spust_smycku(beh, zdroje, FalesnyModel(pis_o), FalesnyModel(hod_o, nazev="gpt-falesny"),
                     hlaseni=_ticho)

    beh2 = Beh.otevri(beh.slozka)
    h2 = hodnoceni(8.0)
    hod2 = FalesnyModel({"hodnoceni_2": [h2], "hodnoceni_3": [hodnoceni(9.5)]}, nazev="gpt-falesny")
    pis2 = FalesnyModel({"posouzeni_2": [posouzeni(h2)], "navrh_3": [text_navrhu(3)]})
    v = spust_smycku(beh2, zdroje, pis2, hod2, hlaseni=_ticho)

    assert v.duvod == "cil_splnen" and v.finalni_verze == 3 and set(v.skore) == {1, 2, 3}
    assert all(not k.startswith(("nalezitosti", "navrh_1", "hodnoceni_1", "posouzeni_1", "navrh_2"))
               for k in _kroky(pis2) + _kroky(hod2))
    assert [p.name for p in sorted(beh.slozka.glob("[0-9][0-9]_*"))] == [
        "01_poptavka.md", "02_nalezitosti.md", "03_navrh_v1.md", "04_hodnoceni_1.md",
        "05_posouzeni_1.md", "06_navrh_v2.md", "06_navrh_v2_zmeny.html", "07_hodnoceni_2.md",
        "08_posouzeni_2.md", "09_navrh_v3.md", "09_navrh_v3_zmeny.html", "10_hodnoceni_3.md"]
    assert beh2.stav.kroky["navrh_1"].cislo == 3 and beh2.stav.kroky["hodnoceni_3"].cislo == 10


def test_obnoveni_zachova_odmitnute_navrhy(tmp_path, zdroje):
    beh = beh_test(tmp_path, zdroje)
    pis_o, hod_o = _odpovedi_se_smisenym_posouzenim([7.0, 9.5])
    hod_o["hodnoceni_2"] = [ChybaModelu("pretizeni", "OpenAI")]
    with pytest.raises(ChybaModelu):
        spust_smycku(beh, zdroje, FalesnyModel(pis_o), FalesnyModel(hod_o, nazev="gpt-falesny"),
                     hlaseni=_ticho)

    hod2 = FalesnyModel({"hodnoceni_2": [hodnoceni(9.5)]}, nazev="gpt-falesny")
    v = spust_smycku(Beh.otevri(beh.slozka), zdroje, FalesnyModel({}), hod2, hlaseni=_ticho)
    assert v.duvod == "cil_splnen"
    instrukce = {k: i for k, i, _ in hod2.volani}
    assert "ODMITNUTO-XYZ" in instrukce["hodnoceni_2"]


def test_spotreba_ulozena_po_kazdem_kroku(tmp_path, zdroje):
    beh = beh_test(tmp_path, zdroje)
    pis_o, hod_o = odpovedi_skriptu([7.0, 9.5])
    hod_o["hodnoceni_2"] = [ChybaModelu("pretizeni", "OpenAI")]
    with pytest.raises(ChybaModelu):
        spust_smycku(beh, zdroje, FalesnyModel(pis_o), FalesnyModel(hod_o, nazev="gpt-falesny"),
                     hlaseni=_ticho)
    # Úspěšně proběhlo 5 volání: nalezitosti, navrh_1, hodnoceni_1, posouzeni_1, navrh_2
    # (zadání uvádí 4 – navrh_2 v tom součtu chybí; hodnoceni_2 spadlo, takže spotřebu nemá).
    ulozeno = Beh.otevri(beh.slozka).stav.spotreba
    assert [s.krok for s in ulozeno] == ["nalezitosti", "navrh_1", "hodnoceni_1", "posouzeni_1", "navrh_2"]


def test_skript_odmitne_neplatne_skore():
    with pytest.raises(ValueError, match="0,5"):
        skript([9.8])


def test_hlaseni_prubehu(tmp_path, zdroje):
    beh = beh_test(tmp_path, zdroje)
    zpravy: list[str] = []
    spust_smycku(beh, zdroje, *skript([7.0, 9.5]), hlaseni=zpravy.append)
    text = "\n".join(zpravy)
    assert "[1/12]" in text and "Hodnocení 1" in text and "skóre" in text
    assert "[3/12] Hodnocení 1" in text and "[6/12] Hodnocení 2" in text
    assert "hotovo, skóre 7,5" in text   # 0,5·7 + 0,35·7 + 0,15·10 = 7,45 → 7,5

from datetime import datetime

from refiner.data import Hodnoceni, Spotreba, VysledekSkore
from refiner.modely.falesne import FalesnyModel
from refiner.smycka import spust_smycku
from refiner.vystup.prehled import vytvor_prehled
from tests.pomocne import beh_test, hodnoceni, kriteria_test, odpovedi_skriptu, skript


def _ticho(_: str) -> None:
    pass


def _html(beh, zdroje) -> str:
    return vytvor_prehled(beh, zdroje.konfigurace).read_text(encoding="utf-8")


def test_prehled_dokonceneho_behu(tmp_path, zdroje):
    beh = beh_test(tmp_path, zdroje)
    v = spust_smycku(beh, zdroje, *skript([7.0, 9.5]), hlaseni=_ticho)
    assert v.duvod == "cil_splnen"
    beh.zapis_pevny("FINALNI_nabidka.md", "# Nabídka\n\nSazba: [DOPLNIT: sazba za MD]\n")
    beh.ukonci("dokoncen", v.duvod, finalni_verze=v.finalni_verze)
    cesta = vytvor_prehled(beh, zdroje.konfigurace)
    assert cesta == beh.slozka / "prehled.html"
    html = cesta.read_text(encoding="utf-8")
    assert "Cíl splněn" in html and "FINALNI_nabidka.docx" in html
    assert "Hodnocení 1" in html and "Hodnocení 2" in html and "9,6" in html


def test_prehled_placeholder_z_finalni_verze(tmp_path, zdroje):
    beh = beh_test(tmp_path, zdroje)
    spust_smycku(beh, zdroje, *skript([9.5]), hlaseni=_ticho)
    beh.zapis_pevny("03_navrh_v1.md", "# Nabídka\n\nSazba: [DOPLNIT: sazba za MD]\n")
    beh.ukonci("dokoncen", "cil_splnen", finalni_verze=1)
    assert "sazba za MD" in _html(beh, zdroje)


def test_prehled_odkazy_na_soubory_kroku(tmp_path, zdroje):
    beh = beh_test(tmp_path, zdroje)
    v = spust_smycku(beh, zdroje, *skript([7.0, 9.5]), hlaseni=_ticho)
    beh.ukonci("dokoncen", v.duvod, finalni_verze=v.finalni_verze)
    html = _html(beh, zdroje)
    for z in beh.stav.kroky.values():
        assert f'href="{z.soubor}"' in html
    assert 'href="04_hodnoceni_1.md"' in html
    assert "_zmeny.html" in html


def test_prehled_preruseneho_behu_bez_hodnoceni(tmp_path, zdroje):
    beh = beh_test(tmp_path, zdroje)
    pisatel, hodnotitel = odpovedi_skriptu([9.5])
    pisatel["nalezitosti"] = [RuntimeError("Spojení vypadlo")]
    try:
        spust_smycku(beh, zdroje, FalesnyModel(pisatel, nazev="c"), FalesnyModel(hodnotitel, nazev="g"),
                     hlaseni=_ticho)
    except Exception:
        pass
    beh.ukonci("prerusen", chyba="Spojení vypadlo")
    html = _html(beh, zdroje)
    assert "Běh byl přerušen" in html and "Spojení vypadlo" in html and "pokracovat.bat" in html


def test_prehled_bezici_stav_bez_ukonceni(tmp_path, zdroje):
    beh = beh_test(tmp_path, zdroje)
    assert "prehled" in vytvor_prehled(beh, zdroje.konfigurace).name


def test_prehled_escapuje_html_z_modelu(tmp_path, zdroje):
    beh = beh_test(tmp_path, zdroje)
    spust_smycku(beh, zdroje, *skript([9.5]), hlaseni=_ticho)
    h = beh.data("hodnoceni_1", Hodnoceni)
    h.kriteria[0].zduvodneni = "<script>alert(1)</script>"
    h.navrhy[0].problem = "<script>alert(2)</script>"
    h.tvrzeni_k_overeni = []
    beh.zapis_pevny("data/04_hodnoceni_1.json", h.model_dump_json())
    beh.zapis_pevny("03_navrh_v1.md", "# N\n\n<script>alert(3)</script> [DOPLNIT: <b>x</b>]\n")
    beh.ukonci("dokoncen", "cil_splnen", finalni_verze=1)
    html = _html(beh, zdroje)
    assert "<script" not in html and "<b>x</b>" not in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html


def test_prehled_tvrzeni_k_overeni_escapovana(tmp_path, zdroje):
    from refiner.data import TvrzeniKOvereni

    beh = beh_test(tmp_path, zdroje)
    spust_smycku(beh, zdroje, *skript([9.5]), hlaseni=_ticho)
    h = beh.data("hodnoceni_1", Hodnoceni)
    h.tvrzeni_k_overeni = [TvrzeniKOvereni(citace="<script>alert(1)</script>", proc="Zákon č. 134/2016")]
    beh.zapis_pevny("data/04_hodnoceni_1.json", h.model_dump_json())
    beh.ukonci("dokoncen", "cil_splnen", finalni_verze=1)
    html = _html(beh, zdroje)
    assert "<script" not in html and "&lt;script&gt;alert(1)" in html and "134/2016" in html


def test_prehled_cena_a_tokeny(tmp_path, zdroje):
    beh = beh_test(tmp_path, zdroje)
    beh.pridej_spotrebu([Spotreba(krok="a", model="claude-opus-5-5", vstup=1_000_000, vystup=0),
                         Spotreba(krok="b", model="claude-opus-5-5", vstup=1_000_000, vystup=0),
                         Spotreba(krok="c", model="neznamy-model", vstup=10, vystup=5)])
    html = _html(beh, zdroje)
    assert "8,00" in html and "orientačně" in html and "cena neznámá" in html


def test_prehled_finalni_neni_posledni_vysvetli(tmp_path, zdroje):
    beh = beh_test(tmp_path, zdroje)
    for k, c in enumerate([6.0, 8.0, 7.0, 7.5], start=1):
        beh.uloz_skore(k, VysledekSkore(a=c, b=c, c=10, celkem=c, cil_splnen=False, duvody_nesplneni=[]))
    beh.ukonci("dokoncen", "limit_revizi", finalni_verze=2)
    html = _html(beh, zdroje)
    assert "vyšší skóre" in html and "verze 2" in html and "Vyčerpán limit" in html


def test_prehled_tabulka_kriterii_a_barvy(tmp_path, zdroje):
    beh = beh_test(tmp_path, zdroje)
    v = spust_smycku(beh, zdroje, *skript([6.0, 9.5]), hlaseni=_ticho)
    beh.ukonci("dokoncen", v.duvod, finalni_verze=v.finalni_verze)
    html = _html(beh, zdroje)
    assert "Celkem" in html and "N1" in html and "B1" in html
    assert "s-cervena" in html and "s-zelena" in html


def test_prehled_stats_navrhu_a_dalsi_kola(tmp_path, zdroje):
    beh = beh_test(tmp_path, zdroje)
    spust_smycku(beh, zdroje, *skript([7.0] * 4, rozhodnuti="castecne"), hlaseni=_ticho)
    beh.ukonci("dokoncen", "limit_revizi", finalni_verze=2)
    assert "Částečně" in _html(beh, zdroje)

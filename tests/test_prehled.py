from datetime import datetime

from refiner.data import Hodnoceni, Spotreba, VysledekSkore
from refiner.models.fakes import FakeModel
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
        spust_smycku(beh, zdroje, FakeModel(pisatel, name="c"), FakeModel(hodnotitel, name="g"),
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


def test_cena_cache_podle_poskytovatele(zdroje):
    """Anthropic: vstup bez cache, zápis ×1,25, čtení ×0,1. OpenAI: cache je podmnožina vstupu, ×0,5."""
    from refiner.vystup.prehled import _cena

    cena = _cena([
        # 4 + 2 000 000×0,1×4 + 400 000×1,25×4 + 100 000×20 (za milion) = 4 + 0,8 + 2 + 2 = 8,80
        Spotreba(krok="a", model="claude-opus-5-5", vstup=1_000_000, vystup=100_000,
                 cache_cteni=2_000_000, cache_zapis=400_000),
        # (1 000 000 − 600 000)×10 + 600 000×0,5×10 + 10 000×50 (za milion) = 4 + 3 + 0,5 = 7,50
        Spotreba(krok="b", model="gpt-6-astra", vstup=1_000_000, vystup=10_000, cache_cteni=600_000),
    ], zdroje.konfigurace)
    assert [r["cena"] for r in cena["radky"]] == ["8,80 USD", "7,50 USD"]
    assert cena["celkem"] == "16,30"


def test_prehled_cena_uvadi_odhad_cache(tmp_path, zdroje):
    beh = beh_test(tmp_path, zdroje)
    beh.pridej_spotrebu([Spotreba(krok="a", model="claude-opus-5-5", vstup=10, vystup=5)])
    html = _html(beh, zdroje)
    assert "Cena (orientačně, cache odhadem)" in html and "bez slev za cache" not in html


def test_prehled_finalni_splnila_cil_vysvetli(tmp_path, zdroje):
    beh = beh_test(tmp_path, zdroje)
    beh.uloz_skore(1, VysledekSkore(a=9.5, b=9.5, c=10, celkem=9.5, cil_splnen=True, duvody_nesplneni=[]))
    beh.uloz_skore(2, VysledekSkore(a=9.8, b=9.8, c=7, celkem=9.6, cil_splnen=False,
                                    duvody_nesplneni=["text obsahuje vymyšlené fakty (1)"]))
    beh.ukonci("dokoncen", "cil_splnen", finalni_verze=1)
    html = _html(beh, zdroje)
    assert "verze 1 splnila cíl" in html and "vyšší skóre" not in html


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


def test_cena_predplatne_se_nepocita(zdroje):
    from refiner.vystup.prehled import _cena, _desetinne

    cena = _cena([Spotreba(krok="navrh", model="claude-opus-5-5", vstup=1000, vystup=500, predplatne=True),
                  Spotreba(krok="hodnoceni_1", model="gpt-6-astra", vstup=1000, vystup=500, predplatne=True)],
                 zdroje.konfigurace)
    assert [r["cena"] for r in cena["radky"]] == ["v předplatném", "v předplatném"]
    assert cena["jen_predplatne"] and cena["predplatne"] and not cena["neznama"]
    assert cena["celkem"] == _desetinne(0.0)


def test_cena_smiseny_beh_rozdeli_radky(zdroje):
    from refiner.vystup.prehled import _cena

    cena = _cena([Spotreba(krok="a", model="claude-opus-5-5", vstup=1_000_000, vystup=0),
                  Spotreba(krok="b", model="claude-opus-5-5", vstup=1000, vystup=500, predplatne=True)],
                 zdroje.konfigurace)
    assert len(cena["radky"]) == 2 and cena["predplatne"] and not cena["jen_predplatne"]
    assert [r["cena"] for r in cena["radky"]] == ["4,00 USD", "v předplatném"]
    assert cena["celkem"] == "4,00"


def test_cena_jen_api_nema_priznaky_predplatneho(zdroje):
    from refiner.vystup.prehled import _cena

    cena = _cena([Spotreba(krok="a", model="claude-opus-5-5", vstup=10, vystup=5)], zdroje.konfigurace)
    assert not cena["predplatne"] and not cena["jen_predplatne"]
    assert not _cena([], zdroje.konfigurace)["jen_predplatne"]


def test_stara_spotreba_bez_pole_je_api():
    assert Spotreba.model_validate({"krok": "x", "model": "m", "vstup": 1, "vystup": 1}).predplatne is False


def test_prehled_celkem_v_predplatnem(tmp_path, zdroje):
    beh = beh_test(tmp_path, zdroje)
    beh.pridej_spotrebu([Spotreba(krok="a", model="claude-opus-5-5", vstup=10, vystup=5, predplatne=True)])
    html = _html(beh, zdroje)
    assert "v předplatném" in html and "0,00 USD" not in html
    assert "se neúčtují po tokenech" in html


def test_prehled_celkem_smiseny(tmp_path, zdroje):
    beh = beh_test(tmp_path, zdroje)
    beh.pridej_spotrebu([Spotreba(krok="a", model="claude-opus-5-5", vstup=1_000_000, vystup=0),
                         Spotreba(krok="b", model="gpt-6-astra", vstup=10, vystup=5, predplatne=True)])
    html = _html(beh, zdroje)
    assert "4,00 USD + část v předplatném" in html


def test_prehled_jen_api_bez_poznamky_o_predplatnem(tmp_path, zdroje):
    beh = beh_test(tmp_path, zdroje)
    beh.pridej_spotrebu([Spotreba(krok="a", model="claude-opus-5-5", vstup=10, vystup=5)])
    assert "předplatném" not in _html(beh, zdroje)

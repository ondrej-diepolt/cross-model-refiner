from refiner.data import Nalezitost, sestav_kriteria
from refiner.konfigurace import KriteriumProfilu
from refiner.skore import format_skore, skore_c, spocitej, vyber_finalni
from tests.pomocne import hodnoceni, kriteria_test, nastaveni_test


def test_skore_c():
    assert [skore_c(n) for n in (0, 1, 2, 3, 4)] == [10, 7, 4, 1, 1]


def test_vazeny_vypocet_a_zaokrouhleni_half_up():
    # 0.5*9 + 0.35*9 + 0.15*10 = 9.15 -> 9.2
    v = spocitej(hodnoceni(9.0), kriteria_test(), nastaveni_test())
    assert (v.a, v.b, v.c, v.celkem) == (9.0, 9.0, 10.0, 9.2)


def test_b_je_vazeny_prumer():
    ostatni = {f"B{i}": 8.0 for i in range(2, 7)}
    v = spocitej(hodnoceni(8.0, {"B1": 10.0, **ostatni}), kriteria_test(), nastaveni_test())
    assert v.b == 8.5


def test_cil_splnen():
    v = spocitej(hodnoceni(9.5), kriteria_test(), nastaveni_test())
    assert v.celkem == 9.6 and v.cil_splnen and v.duvody_nesplneni == []


def test_cil_blokuje_nalezitost_pod_8():
    v = spocitej(hodnoceni(10.0, {"N2": 7.5}), kriteria_test(), nastaveni_test())
    assert not v.cil_splnen
    assert any("N2" in d for d in v.duvody_nesplneni)


def test_cil_blokuje_vymysleny_fakt():
    v = spocitej(hodnoceni(10.0, fakta=1), kriteria_test(), nastaveni_test())
    assert v.celkem == 9.6 and not v.cil_splnen
    assert any("vymyšlen" in d for d in v.duvody_nesplneni)


def test_cil_pod_prahem():
    v = spocitej(hodnoceni(9.2), kriteria_test(), nastaveni_test())
    assert v.celkem == 9.3 and not v.cil_splnen
    assert any("9,3 < 9,5" in d for d in v.duvody_nesplneni)


def test_vyber_finalni_nejvyssi_pri_shode_pozdejsi():
    assert vyber_finalni({1: 7.0, 2: 8.8, 3: 8.1, 4: 8.8}) == 4
    assert vyber_finalni({1: 7.0, 2: 8.8, 3: 8.1}) == 2


def test_format_skore():
    assert format_skore(9.5) == "9,5" and format_skore(10.0) == "10,0"


def test_sestav_kriteria_poradi_a_skupiny():
    nal = [Nalezitost(id=f"N{i}", text=f"text {i}", citace=f"cit {i}") for i in (1, 2)]
    prof = [KriteriumProfilu(id="B1", nazev="n", popis="p", vaha=0.4)]
    k = sestav_kriteria(nal, prof)
    assert [x.id for x in k] == ["N1", "N2", "B1"]
    assert [x.skupina for x in k] == ["A", "A", "B"]
    assert k[0].nazev == "text 1" and k[0].popis == "cit 1" and k[0].vaha == 1
    assert k[2].vaha == 0.4

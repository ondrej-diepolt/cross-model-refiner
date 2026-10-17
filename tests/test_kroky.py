import pytest

from refiner.data import Hodnoceni, Navrh, Posouzeni, Rozhodnuti, Nalezitost
from refiner.konfigurace import ChybaKonfigurace
from refiner.kroky import (
    extrahuj_nalezitosti,
    napis_navrh,
    ohodnot,
    posud,
    prijate,
    vykresli_prompt,
    zapracuj,
    zkontroluj_hodnoceni,
    zkontroluj_posouzeni,
    zkontroluj_prepis,
)
from refiner.modely.chyby import ChybaModelu
from refiner.modely.falesne import FalesnyModel
from tests.pomocne import hodnoceni, kriteria_test, posouzeni

PROMENNE = {
    "nalezitosti": ["poptavka"],
    "navrh": ["typ_dokumentu", "pokyny_struktura", "poptavka", "podklady", "nalezitosti", "kriteria"],
    "hodnoceni": ["typ_dokumentu", "poptavka", "podklady", "kriteria", "max_navrhu", "odmitnute"],
    "posouzeni": ["poptavka", "podklady", "nalezitosti"],
    "zapracovani": ["poptavka", "podklady", "nalezitosti"],
}

NALEZITOSTI = [
    Nalezitost(id="N1", text="Metodika", citace="popis metodiky cvičení"),
    Nalezitost(id="N2", text="Harmonogram", citace="harmonogram a hlavní milníky realizace"),
    Nalezitost(id="N3", text="Cena", citace="cenu za celé plnění"),
]


def _navrh(id_: str, priorita: str = "stredni", text: str = "Nové znění.") -> Navrh:
    return Navrh(id=id_, kriterium="B1", misto="kap. 1", problem="Problém.", navrh=text, priorita=priorita)


def _rozhodnuti(id_: str, rozhodnuti: str, jak: str = "Takto.", zduvodneni: str = "Zdůvodnění.") -> Rozhodnuti:
    return Rozhodnuti(id_navrhu=id_, opora="Opora.", predpoklad="Předpoklad.", dusledek="Důsledek.",
                      rozhodnuti=rozhodnuti, zduvodneni=zduvodneni, jak_zapracovat=jak)


# ---------------------------------------------------------------- prompty

def test_vsechny_prompty_se_vykresli(koren_repa):
    for nazev, promenne in PROMENNE.items():
        hodnoty = {p: f"«{p.upper()}»" for p in promenne}
        text = vykresli_prompt(koren_repa / "prompty", nazev, **hodnoty)
        assert "${" not in text, nazev
        for p, h in hodnoty.items():
            assert h in text, f"{nazev}.md nepoužívá proměnnou {p}"


def test_chybejici_promenna_v_promptu(tmp_path):
    (tmp_path / "pokus.md").write_text("Ahoj ${jmeno} a ${neznama}.", encoding="utf-8")
    with pytest.raises(ChybaKonfigurace) as e:
        vykresli_prompt(tmp_path, "pokus", jmeno="Petr")
    assert "pokus.md" in str(e.value) and "neznama" in str(e.value)


def test_prompt_s_dolarem_se_vykresli(tmp_path):
    (tmp_path / "pokus.md").write_text("Cena $$100 pro ${jmeno}.", encoding="utf-8")
    assert vykresli_prompt(tmp_path, "pokus", jmeno="Petr") == "Cena $100 pro Petr."


# ---------------------------------------------------------------- náležitosti

def test_nalezitosti_zahodi_vymyslenou_citaci(zdroje):
    m = FalesnyModel({"nalezitosti": [{"nalezitosti": [
        {"id": "N1", "text": "Harmonogram", "citace": "harmonogram a hlavní milníky realizace"},
        {"id": "N2", "text": "Pojištění", "citace": "doklad o pojištění odpovědnosti"}]}]})
    n, var = extrahuj_nalezitosti(m, zdroje)
    assert [x.id for x in n] == ["N1"] and "N2" in var[0]
    assert len(m.volani) == 1


def test_nalezitosti_citace_s_jinymi_mezerami_projde(zdroje):
    m = FalesnyModel({"nalezitosti": [{"nalezitosti": [
        {"id": "N1", "text": "Harmonogram", "citace": "harmonogram  a hlavní\nmilníky realizace"}]}]})
    n, var = extrahuj_nalezitosti(m, zdroje)
    assert [x.id for x in n] == ["N1"] and var == []


def test_nalezitosti_zadna_platna_ani_po_oprave(zdroje):
    spatne = {"nalezitosti": [{"id": "N1", "text": "X", "citace": "vymyšlená věta"}]}
    m = FalesnyModel({"nalezitosti": [spatne, spatne]})
    with pytest.raises(ChybaModelu) as e:
        extrahuj_nalezitosti(m, zdroje)
    assert e.value.druh == "nevalidni_vystup" and e.value.sluzba == "Anthropic"
    assert len(m.volani) == 2 and "## Oprava" in m.volani[1][2]


def test_nalezitosti_pouziji_effort_extrakce(zdroje):
    class Zaznamovy(FalesnyModel):
        def json(self, instrukce, zadani, schema, *, krok, effort=None):
            self.effort = effort
            return super().json(instrukce, zadani, schema, krok=krok, effort=effort)

    m = Zaznamovy({"nalezitosti": [{"nalezitosti": [
        {"id": "N1", "text": "Harmonogram", "citace": "harmonogram a hlavní milníky realizace"}]}]})
    extrahuj_nalezitosti(m, zdroje)
    assert m.effort == "medium"
    assert "harmonogram a hlavní milníky realizace" in m.volani[0][1]


# ---------------------------------------------------------------- návrh

def test_navrh_dostane_zdroje_a_bez_podkladu_pokyn_doplnit(zdroje):
    m = FalesnyModel({"navrh": ["# Nabídka\n\nText."]})
    assert napis_navrh(m, zdroje, NALEZITOSTI) == "# Nabídka\n\nText."
    krok, instrukce, _ = m.volani[0]
    assert krok == "navrh_1"
    assert "harmonogram a hlavní milníky realizace" in instrukce
    assert "Profil firmy nebyl dodán" in instrukce
    assert "B1" in instrukce and "N3" in instrukce


# ---------------------------------------------------------------- hodnocení

def test_hodnoceni_chybejici_kriterium_opravi_druhym_volanim(zdroje):
    krit = kriteria_test()
    bez_b3 = hodnoceni(8, kriteria=[k for k in krit if k.id != "B3"])
    m = FalesnyModel({"hodnoceni": [bez_b3, hodnoceni(8)]}, nazev="gpt-6-astra")
    h, var = ohodnot(m, zdroje, krit, "# Dokument", [], "hodnoceni_1")
    assert {s.id for s in h.kriteria} == {k.id for k in krit} and var == []
    assert len(m.volani) == 2
    zadani2 = m.volani[1][2]
    assert "## Oprava" in zadani2 and "B3" in zadani2
    assert "## Dokument" in m.volani[0][2] and "## Oprava" not in m.volani[0][2]


def test_hodnoceni_oprava_po_nevalidnim_vystupu_modelu(zdroje):
    chyba = ChybaModelu("nevalidni_vystup", "OpenAI", detail="neplatný JSON", surova_odpoved="{")
    m = FalesnyModel({"hodnoceni": [chyba, hodnoceni(8)]}, nazev="gpt-6-astra")
    h, _ = ohodnot(m, zdroje, kriteria_test(), "# Dokument", [], "hodnoceni_1")
    assert len(m.volani) == 2 and "neplatný JSON" in m.volani[1][2]


def test_hodnoceni_jina_chyba_modelu_se_neopakuje(zdroje):
    m = FalesnyModel({"hodnoceni": [ChybaModelu("pretizeni", "OpenAI"), hodnoceni(8)]}, nazev="gpt-6-astra")
    with pytest.raises(ChybaModelu) as e:
        ohodnot(m, zdroje, kriteria_test(), "# Dokument", [], "hodnoceni_1")
    assert e.value.druh == "pretizeni" and len(m.volani) == 1


def test_hodnoceni_dvakrat_neplatne_vyhodi_chybu_se_surovou_odpovedi(zdroje):
    krit = kriteria_test()
    bez_b3 = hodnoceni(8, kriteria=[k for k in krit if k.id != "B3"])
    m = FalesnyModel({"hodnoceni": [bez_b3, bez_b3]}, nazev="gpt-6-astra")
    with pytest.raises(ChybaModelu) as e:
        ohodnot(m, zdroje, krit, "# Dokument", [], "hodnoceni_1")
    assert e.value.druh == "nevalidni_vystup" and e.value.sluzba == "OpenAI"
    assert "B3" in e.value.detail
    assert e.value.surova_odpoved and Hodnoceni.model_validate_json(e.value.surova_odpoved) == bez_b3


def test_hodnoceni_platne():
    assert zkontroluj_hodnoceni(hodnoceni(8, {"B2": 7.5, "N1": 10, "N2": 1}), kriteria_test()) == []


def test_hodnoceni_skore_mimo_rozsah():
    chyby = zkontroluj_hodnoceni(hodnoceni(8, {"N1": 11}), kriteria_test())
    assert chyby != [] and "N1" in chyby[0]


def test_hodnoceni_skore_ne_nasobek_pul():
    chyby = zkontroluj_hodnoceni(hodnoceni(8, {"B2": 7.3}), kriteria_test())
    assert chyby != [] and "B2" in chyby[0]


def test_hodnoceni_kriterium_navic_a_dvakrat():
    h = hodnoceni(8)
    h.kriteria.append(h.kriteria[0].model_copy(update={"id": "X9"}))
    h.kriteria.append(h.kriteria[1].model_copy())
    chyby = " ".join(zkontroluj_hodnoceni(h, kriteria_test()))
    assert "X9" in chyby and h.kriteria[1].id in chyby


def test_hodnoceni_duplicitni_id_navrhu_a_nezname_kriterium():
    h = hodnoceni(8)
    h.navrhy = [_navrh("H1"), _navrh("H1"), _navrh("H2").model_copy(update={"kriterium": "Z7"})]
    chyby = " ".join(zkontroluj_hodnoceni(h, kriteria_test()))
    assert "H1" in chyby and "Z7" in chyby


def test_hodnoceni_orizne_navrhy_podle_priority(zdroje):
    priority = ["nizka", "stredni"] * 4 + ["vysoka", "nizka", "vysoka", "vysoka"]
    h = hodnoceni(8)
    h.navrhy = [_navrh(f"H{i}", p) for i, p in enumerate(priority, start=1)]
    m = FalesnyModel({"hodnoceni": [h]}, nazev="gpt-6-astra")
    vysledek, var = ohodnot(m, zdroje, kriteria_test(), "# Dokument", [], "hodnoceni_1")
    ids = [n.id for n in vysledek.navrhy]
    assert len(ids) == 10
    assert {"H9", "H11", "H12"} <= set(ids)
    assert var and "12" in var[0]
    # dvě vypadlé jsou poslední dvě „nizka“
    assert set(n.id for n in h.navrhy) - set(ids) == {"H7", "H10"}


def test_odmitnute_navrhy_jsou_v_instrukci(zdroje):
    odm = [(_navrh("H1-02", text="Přidat certifikaci ISO 27001."),
            _rozhodnuti("H1-02", "odmitnuto", zduvodneni="Certifikace není v podkladech."))]
    m = FalesnyModel({"hodnoceni": [hodnoceni(8)]}, nazev="gpt-6-astra")
    ohodnot(m, zdroje, kriteria_test(), "# Dokument", odm, "hodnoceni_2")
    instrukce = m.volani[0][1]
    assert "Přidat certifikaci ISO 27001." in instrukce
    assert "Certifikace není v podkladech." in instrukce


def test_bez_odmitnutych_je_v_instrukci_zadne(zdroje):
    m = FalesnyModel({"hodnoceni": [hodnoceni(8)]}, nazev="gpt-6-astra")
    ohodnot(m, zdroje, kriteria_test(), "# Dokument", [], "hodnoceni_1")
    assert "(žádné)" in m.volani[0][1]


# ---------------------------------------------------------------- posouzení

def test_posouzeni_chybejici_rozhodnuti():
    h = hodnoceni(8, navrhy=3)
    p = posouzeni(h)
    p.rozhodnuti = p.rozhodnuti[:2]
    chyby = zkontroluj_posouzeni(p, h)
    assert chyby != [] and "V3" in " ".join(chyby)


def test_posouzeni_nezname_a_duplicitni_id():
    h = hodnoceni(8, navrhy=2)
    p = posouzeni(h)
    p.rozhodnuti.append(_rozhodnuti("V1", "prijato"))
    p.rozhodnuti.append(_rozhodnuti("V9", "prijato"))
    chyby = " ".join(zkontroluj_posouzeni(p, h))
    assert "V1" in chyby and "V9" in chyby
    assert zkontroluj_posouzeni(posouzeni(h), h) == []


def test_posud_opravi_chybejici_rozhodnuti(zdroje):
    h = hodnoceni(8, navrhy=3)
    neuplne = posouzeni(h)
    neuplne.rozhodnuti = neuplne.rozhodnuti[:2]
    m = FalesnyModel({"posouzeni": [neuplne, posouzeni(h)]}, nazev="claude-opus-5-5")
    p = posud(m, zdroje, NALEZITOSTI, "# Dokument", h, "posouzeni_1")
    assert len(p.rozhodnuti) == 3 and len(m.volani) == 2
    _, instrukce, zadani = m.volani[0]
    assert "## Dokument" in zadani and "## Návrhy hodnotitele" in zadani and "V3" in zadani
    assert "harmonogram a hlavní milníky realizace" in instrukce
    assert "V3" in m.volani[1][2] and "## Oprava" in m.volani[1][2]


def test_prijate_vraci_prijato_a_castecne():
    p = Posouzeni(rozhodnuti=[_rozhodnuti("A", "prijato"), _rozhodnuti("B", "odmitnuto"),
                              _rozhodnuti("C", "castecne")], shrnuti="")
    assert [r.id_navrhu for r in prijate(p)] == ["A", "C"]


# ---------------------------------------------------------------- přepis

def test_prepis_zmizel_nadpis():
    h = hodnoceni(8)
    p = posouzeni(h)
    chyby = zkontroluj_prepis("# A\n# B\nx", "# A\nx", h, p)
    assert chyby != [] and "# B" in chyby[0]


def test_prepis_prazdny():
    h = hodnoceni(8)
    assert zkontroluj_prepis("# A\nx", "  \n", h, posouzeni(h)) != []


def test_prepis_zkraceni_bez_navrhu():
    h = hodnoceni(8)
    stary = "# A\n" + "x" * 196
    novy = "# A\n" + "x" * 96
    assert zkontroluj_prepis(stary, novy, h, posouzeni(h)) != []


def test_prepis_zkraceni_s_navrhem():
    h = hodnoceni(8, navrhy=1)
    h.navrhy[0].navrh = "Zkrátit kap. 3 na polovinu."
    stary = "# A\n" + "x" * 196
    novy = "# A\n" + "x" * 96
    assert zkontroluj_prepis(stary, novy, h, posouzeni(h)) == []


@pytest.mark.parametrize("text", [
    "Odstraňte duplicitní odstavec v kap. 2.",
    "zkrať úvod na tři věty",
    "ZKRAŤTE shrnutí.",
    "Vypusťte kapitolu 4.",
    "Smažte opakovaný popis týmu.",
    "Zrušte přílohu B.",
])
def test_prepis_zkraceni_s_navrhem_s_diakritikou(text):
    h = hodnoceni(8, navrhy=1)
    h.navrhy[0].navrh = text
    stary = "# A\n" + "x" * 196
    novy = "# A\n" + "x" * 96
    assert zkontroluj_prepis(stary, novy, h, posouzeni(h)) == []


def test_prepis_zkraceni_jak_zapracovat_s_diakritikou():
    h = hodnoceni(8, navrhy=1)
    p = posouzeni(h)
    p.rozhodnuti[0].jak_zapracovat = "Odstraň opakovaný odstavec."
    stary = "# A\n" + "x" * 196
    novy = "# A\n" + "x" * 96
    assert zkontroluj_prepis(stary, novy, h, p) == []


def test_prepis_zkraceni_s_odmitnutym_navrhem_neplati():
    h = hodnoceni(8, navrhy=1)
    h.navrhy[0].navrh = "Odstranit kap. 3."
    stary = "# A\n" + "x" * 196
    novy = "# A\n" + "x" * 96
    assert zkontroluj_prepis(stary, novy, h, posouzeni(h, "odmitnuto")) != []


def test_zapracovani_dostane_jen_prijate(zdroje):
    h = hodnoceni(8, navrhy=0)
    h.navrhy = [_navrh("H1", text="PRIJATY text"), _navrh("H2", text="ODMITNUTY text"),
                _navrh("H3", text="CASTECNY text")]
    p = Posouzeni(rozhodnuti=[_rozhodnuti("H1", "prijato", jak="Doplnit tabulku."),
                              _rozhodnuti("H2", "odmitnuto", jak="-"),
                              _rozhodnuti("H3", "castecne", jak="Jen první větu.")], shrnuti="")
    stary = "# Nabídka\n\n" + "Původní text. " * 10
    m = FalesnyModel({"navrh": [stary + " Doplněno."]}, nazev="claude-opus-5-5")
    novy = zapracuj(m, zdroje, NALEZITOSTI, stary, h, p, "navrh_2")
    assert novy == stary + " Doplněno."
    krok, instrukce, zadani = m.volani[0]
    assert krok == "navrh_2"
    assert "## Dokument" in zadani and "## Přijaté návrhy k zapracování" in zadani
    assert "PRIJATY text" in zadani and "CASTECNY text" in zadani
    assert "Doplnit tabulku." in zadani and "Jen první větu." in zadani
    assert "ODMITNUTY text" not in zadani
    assert "harmonogram a hlavní milníky realizace" in instrukce


def test_zapracovani_ztraceny_nadpis_opravi(zdroje):
    h = hodnoceni(8, navrhy=1)
    p = posouzeni(h)
    stary = "# A\ntext\n# B\ntext"
    m = FalesnyModel({"navrh": ["# A\ntext\ntext", stary + "\nnové"]}, nazev="claude-opus-5-5")
    assert zapracuj(m, zdroje, NALEZITOSTI, stary, h, p, "navrh_2") == stary + "\nnové"
    assert len(m.volani) == 2 and "# B" in m.volani[1][2] and "## Oprava" in m.volani[1][2]


def test_zapracovani_dvakrat_spatne(zdroje):
    h = hodnoceni(8, navrhy=1)
    p = posouzeni(h)
    m = FalesnyModel({"navrh": ["", ""]}, nazev="claude-opus-5-5")
    with pytest.raises(ChybaModelu) as e:
        zapracuj(m, zdroje, NALEZITOSTI, "# A\ntext", h, p, "navrh_2")
    assert e.value.druh == "nevalidni_vystup" and e.value.sluzba == "Anthropic"
    assert e.value.surova_odpoved == ""

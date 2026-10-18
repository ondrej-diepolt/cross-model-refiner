import textwrap

import pytest

from refiner.konfigurace import (
    ChybaKonfigurace,
    cesta_kriterii_k_poptavce,
    dostupne_profily,
    nacti_konfiguraci,
    nacti_nastaveni,
)

NASTAVENI = """\
modely:
  claude: {model: c, effort: high, effort_extrakce: medium, max_tokens_text: 10, max_tokens_json: 5, fallback: true}
  gpt: {model: g, effort: high, max_output_tokens: 10}
  max_retries: 4
  timeout_s: 600
smycka: {cilove_skore: 9.5, max_revizi: 3, min_nalezitost: 8, max_navrhu: 10}
vahy_skupin: {A: 0.5, B: 0.35, C: 0.15}
vychozi_profil: nabidka
ceny_usd_za_milion:
  c: {vstup: 1.0, vystup: 2.0}
"""


def _zapis(cesta, text):
    cesta.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    return cesta


def _profil(tmp_path, kriteria=None, hlavicka=None):
    hlavicka = hlavicka or "nazev: P\ntyp_dokumentu: x\npokyny_struktura: osnova\n"
    kriteria = kriteria or (
        "kriteria:\n"
        "  - id: B1\n    nazev: Prvni\n    popis: p\n    vaha: 0.5\n"
        "  - id: B2\n    nazev: Druhe\n    popis: p\n    vaha: 0.5\n"
    )
    return _zapis(tmp_path / "profil.yaml", hlavicka + kriteria)


def _nastaveni(tmp_path, nahrad=None):
    text = NASTAVENI
    for a, b in (nahrad or {}).items():
        assert a in text
        text = text.replace(a, b)
    return _zapis(tmp_path / "nastaveni.yaml", text)


def test_nacte_repo_konfiguraci(koren_repa):
    k = nacti_konfiguraci(koren_repa / "nastaveni.yaml", koren_repa / "profily" / "nabidka.yaml")
    assert k.nastaveni.smycka.cilove_skore == 9.5 and k.nastaveni.smycka.max_revizi == 3
    assert k.nastaveni.modely.claude.model == "claude-opus-5-5"
    # Uvažování se počítá do limitů výstupu; nízké limity končily uříznutou odpovědí.
    assert k.nastaveni.modely.claude.max_tokens_json == 32000
    assert k.nastaveni.modely.gpt.max_output_tokens == 64000 and k.nastaveni.modely.timeout_s == 1800
    assert [c.id for c in k.kriteria_profilu] == ["B1", "B2", "B3", "B4", "B5", "B6"]
    assert k.profil_nazev == "nabidka"


def test_vaha_textem_hlasi_soubor_radek_a_cesky(tmp_path):
    profil = _zapis(
        tmp_path / "profil.yaml",
        """\
        nazev: P
        typ_dokumentu: x
        pokyny_struktura: osnova
        kriteria:
          - id: B1
            nazev: Prvni
            popis: p
            vaha: 0.5
          - id: B2
            nazev: Druhe
            popis: p
            vaha: vysoká
        """,
    )
    with pytest.raises(ChybaKonfigurace) as e:
        nacti_konfiguraci(_nastaveni(tmp_path), profil)
    assert "profil.yaml" in str(e.value) and "řádek 12" in str(e.value)
    assert "musí být číslo" in str(e.value) and "vysoká" in str(e.value)


def test_neznama_polozka_preklep(tmp_path):
    profil = _profil(
        tmp_path,
        hlavicka="nazev: P\ntyp_dokumentu: x\npokyny_struktura: o\nkriterja: []\n",
        kriteria="kriteria: []\n",
    )
    with pytest.raises(ChybaKonfigurace) as e:
        nacti_konfiguraci(_nastaveni(tmp_path), profil)
    assert "neznámá položka" in str(e.value) and "kriterja" in str(e.value)


def test_chybejici_povinna_polozka(tmp_path):
    nast = _nastaveni(tmp_path, {"cilove_skore: 9.5, ": ""})
    with pytest.raises(ChybaKonfigurace) as e:
        nacti_konfiguraci(nast, _profil(tmp_path))
    assert "chybí povinná položka" in str(e.value) and "cilove_skore" in str(e.value)
    assert "nastaveni.yaml" in str(e.value)


@pytest.mark.parametrize("puvodni,preklep,cesta", [
    ("claude: {model: c, effort: high", "claude: {model: c, effort: hihg", "modely.claude.effort"),
    ("effort_extrakce: medium", "effort_extrakce: stredni", "modely.claude.effort_extrakce"),
    ("gpt: {model: g, effort: high", "gpt: {model: g, effort: maximum", "modely.gpt.effort"),
    # „minimal“ zná jen OpenAI, ne Anthropic.
    ("claude: {model: c, effort: high", "claude: {model: c, effort: minimal", "modely.claude.effort"),
])
def test_neplatny_effort_hlasi_cesky(tmp_path, puvodni, preklep, cesta):
    nast = _nastaveni(tmp_path, {puvodni: preklep})
    with pytest.raises(ChybaKonfigurace) as e:
        nacti_konfiguraci(nast, _profil(tmp_path))
    zprava = str(e.value)
    assert "nastaveni.yaml, řádek" in zprava and cesta in zprava
    assert "musí být jedna z" in zprava and "'xhigh' nebo 'max'" in zprava
    assert " or " not in zprava


def test_effort_hodnoty_podle_sdk(tmp_path):
    nast = _nastaveni(tmp_path, {"claude: {model: c, effort: high": "claude: {model: c, effort: xhigh",
                                 "gpt: {model: g, effort: high": "gpt: {model: g, effort: minimal"})
    k = nacti_konfiguraci(nast, _profil(tmp_path))
    assert k.nastaveni.modely.claude.effort == "xhigh"
    assert k.nastaveni.modely.gpt.effort == "minimal"


def test_vahy_skupin_musi_dat_soucet_1(tmp_path):
    nast = _nastaveni(tmp_path, {"{A: 0.5, B: 0.35, C: 0.15}": "{A: 0.5, B: 0.5, C: 0.15}"})
    with pytest.raises(ChybaKonfigurace) as e:
        nacti_konfiguraci(nast, _profil(tmp_path))
    assert "součet" in str(e.value)


def test_neplatny_yaml_hlasi_radek(tmp_path):
    profil = _zapis(tmp_path / "profil.yaml", "nazev: P\nkriteria: [a, b\ntyp: x\n")
    with pytest.raises(ChybaKonfigurace) as e:
        nacti_konfiguraci(_nastaveni(tmp_path), profil)
    assert "řádek" in str(e.value) and "profil.yaml" in str(e.value)


def test_kriteria_k_poptavce_pridaji_a_prevazi(tmp_path, koren_repa):
    kr = _zapis(
        tmp_path / "a.kriteria.yaml",
        """\
        kriteria_navic:
          - id: X1
            nazev: Navic
            popis: p
            vaha: 0.1
        vahy: {B6: 0.05}
        """,
    )
    k = nacti_konfiguraci(koren_repa / "nastaveni.yaml", koren_repa / "profily" / "nabidka.yaml", kr)
    ids = [c.id for c in k.kriteria_profilu]
    assert ids[-1] == "X1"
    assert next(c for c in k.kriteria_profilu if c.id == "B6").vaha == 0.05
    assert [c.id for c in k.profil.kriteria] == ["B1", "B2", "B3", "B4", "B5", "B6"]
    assert next(c for c in k.profil.kriteria if c.id == "B6").vaha == 0.10


def test_kriteria_k_poptavce_neznamy_id_ve_vahach(tmp_path, koren_repa):
    kr = _zapis(tmp_path / "a.kriteria.yaml", "vahy: {B9: 0.1}\n")
    with pytest.raises(ChybaKonfigurace) as e:
        nacti_konfiguraci(koren_repa / "nastaveni.yaml", koren_repa / "profily" / "nabidka.yaml", kr)
    assert "B9" in str(e.value)


def test_id_kriteria_nesmi_zacinat_N(tmp_path):
    profil = _profil(
        tmp_path,
        kriteria="kriteria:\n  - id: N1\n    nazev: A\n    popis: p\n    vaha: 1\n",
    )
    with pytest.raises(ChybaKonfigurace) as e:
        nacti_konfiguraci(_nastaveni(tmp_path), profil)
    assert "N" in str(e.value) and "vyhrazen" in str(e.value)


def test_duplicitni_id_kriteria(tmp_path):
    profil = _profil(
        tmp_path,
        kriteria=(
            "kriteria:\n"
            "  - id: B1\n    nazev: A\n    popis: p\n    vaha: 1\n"
            "  - id: B1\n    nazev: B\n    popis: p\n    vaha: 1\n"
        ),
    )
    with pytest.raises(ChybaKonfigurace) as e:
        nacti_konfiguraci(_nastaveni(tmp_path), profil)
    assert "duplicitní" in str(e.value) and "B1" in str(e.value)


def test_cesta_kriterii_k_poptavce(tmp_path):
    vstup = tmp_path / "a.docx"
    vstup.write_bytes(b"")
    assert cesta_kriterii_k_poptavce(vstup) is None
    kr = _zapis(tmp_path / "a.kriteria.yaml", "vahy: {}\n")
    assert cesta_kriterii_k_poptavce(vstup) == kr


def test_dostupne_profily(koren_repa):
    assert dostupne_profily(koren_repa / "profily") == ["nabidka", "smernice"]


def test_vychozi_rezim_je_predplatne(koren_repa):
    n = nacti_nastaveni(koren_repa / "nastaveni.yaml")
    assert n.modely.rezim == "predplatne"
    assert n.modely.predplatne.claude.model == "claude-opus-5-5"
    assert n.modely.predplatne.codex.model == "gpt-6-astra"
    assert n.modely.predplatne.claude.prikaz is None


def test_stara_kopie_bez_rezimu_se_nacte(tmp_path):
    n = nacti_nastaveni(_nastaveni(tmp_path))
    assert n.modely.rezim == "predplatne" and n.modely.predplatne.codex.effort == "high"


@pytest.mark.parametrize("effort", ["ultra", "none", "minimal"])
def test_codex_effort_mimo_povolene_selze(tmp_path, effort):
    soubor = _nastaveni(tmp_path, {"modely:\n": f"modely:\n  predplatne: {{codex: {{effort: {effort}}}}}\n"})
    with pytest.raises(ChybaKonfigurace, match="modely.predplatne.codex.effort"):
        nacti_nastaveni(soubor)


def test_neznamy_rezim_selze(tmp_path):
    soubor = _nastaveni(tmp_path, {"modely:\n": "modely:\n  rezim: xyz\n"})
    with pytest.raises(ChybaKonfigurace, match="modely.rezim"):
        nacti_nastaveni(soubor)


def test_effort_extrakce_predplatneho_se_projevi_v_oddilu_claude(tmp_path):
    """kroky.py čte effort_extrakce z modely.claude; v režimu predplatne musí platit hodnota z predplatne."""
    soubor = _nastaveni(tmp_path, {"modely:\n": "modely:\n  predplatne: {claude: {effort_extrakce: low}}\n"})
    n = nacti_nastaveni(soubor)
    assert n.modely.claude.effort_extrakce == "low"


def test_effort_extrakce_api_rezimu_zustava(tmp_path):
    soubor = _nastaveni(tmp_path, {"modely:\n": "modely:\n  rezim: api\n  predplatne: {claude: {effort_extrakce: low}}\n"})
    assert nacti_nastaveni(soubor).modely.claude.effort_extrakce == "medium"

"""Porovnání s referencí (design kap. 11)."""
import io
import os
import shutil
from pathlib import Path

import pytest

from refiner.run import Run
from refiner.cli import main
from refiner.data import Evaluation
from refiner.models.errors import ModelError
from refiner.models.fakes import FakeModel, demo_models
from refiner.porovnani import (
    OTAZKY_FORMULARE,
    Coverage,
    ElementCoverage,
    ReferenceElement,
    ReferenceElements,
    PairComparison,
    CriterionComparison,
    ComparisonResult,
    najdi_referenci,
    porovnej,
    zkombinuj_srovnani,
)
from refiner.loop import run_loop
from refiner.input import InputError
from tests.helpers import TEST_REQUEST, make_run, make_evaluation, make_criteria, scripted_models

ZNACKA = "REFERENCNI-ZNACKA"
REFERENCE = f"# Nabídka dodavatele\n\nRučně dotažená nabídka {ZNACKA}.\n"
KROKY = ['comparison_calibration', 'comparison_pair_1', 'comparison_pair_2',
         'comparison_elements', 'comparison_coverage']


def k(id_: str, lepsi: str, zduvodneni: str = "Zdůvodnění.") -> CriterionComparison:
    return CriterionComparison(id=id_, better=lepsi, rationale=zduvodneni)


def _prvky(*popisy: str) -> ReferenceElements:
    return ReferenceElements(elements=[ReferenceElement(id=f"P{i}", description=p) for i, p in enumerate(popisy, start=1)])


def _pokryti(*stavy: tuple[str, str]) -> Coverage:
    return Coverage(items=[ElementCoverage(id=f"P{i}", status=s, comment=c)
                            for i, (s, c) in enumerate(stavy, start=1)])


def _hodnotitel(**overrides) -> FakeModel:
    """Falešný hodnotitel pro 5 kroků porovnání; kritéria = N1–N3 + kritéria profilu."""
    ids = [x.id for x in make_criteria(3)]
    odpovedi = {
        'comparison_calibration': [make_evaluation(9.0, suggestions=0)],
        'comparison_pair_1': [PairComparison(criteria=[k(i, "A") for i in ids])],
        'comparison_pair_2': [PairComparison(criteria=[k(i, "B") for i in ids])],
        'comparison_elements': [_prvky("Závazný cenový strop", "Kritéria převzetí po etapách", "Definice vady")],
        'comparison_coverage': [_pokryti(('present', "Kap. 2."), ('missing', "Nikde."), ('partial', "Jen obecně."))],
    }
    odpovedi.update(overrides)
    return FakeModel(odpovedi, name="gpt-falesny")


def _dokonceny_beh(tmp_path: Path, sources) -> tuple[Run, FakeModel]:
    beh = make_run(tmp_path, sources)
    pisatel, hod = scripted_models([9.5])
    vysledek = run_loop(beh, sources, pisatel, hod, lambda _: None)
    beh.finish('completed', vysledek.reason, final_version=vysledek.final_version)
    return beh, pisatel


def _ticho(_: str) -> None:
    pass


# ---------------------------------------------------------------- čisté funkce

def test_zkombinuj_srovnani():
    s1 = PairComparison(criteria=[k("B1", "A"), k("B2", "B"), k("B3", "A"), k("B4", 'tie')])
    s2 = PairComparison(criteria=[k("B1", "B"), k("B2", "A"), k("B3", "A"), k("B4", 'tie')])
    assert zkombinuj_srovnani(s1, s2) == {
        "B1": 'generated', "B2": "reference", "B3": 'tie', "B4": 'tie'}


def test_zkombinuj_srovnani_stejne_v_jednom_poradi_je_nerozhodne():
    s1 = PairComparison(criteria=[k("B1", "A")])
    s2 = PairComparison(criteria=[k("B1", 'tie')])
    assert zkombinuj_srovnani(s1, s2) == {"B1": 'tie'}


@pytest.mark.parametrize("soubory", [["reference.docx"], ["Nabídka NRB.md"]])
def test_najdi_referenci_jeden_soubor(tmp_path, soubory):
    (tmp_path / "examples").mkdir()
    for n in soubory:
        (tmp_path / "examples" / n).write_text("x", encoding="utf-8")
    (tmp_path / "examples" / "~$docasny.docx").write_text("x", encoding="utf-8")
    assert najdi_referenci(tmp_path) == tmp_path / "examples" / soubory[0]


@pytest.mark.parametrize("soubory", [[], ["a.md", "b.docx"], None])
def test_najdi_referenci_jinak_chyba(tmp_path, soubory):
    if soubory is not None:
        (tmp_path / "examples").mkdir()
        for n in soubory:
            (tmp_path / "examples" / n).write_text("x", encoding="utf-8")
    with pytest.raises(InputError) as e:
        najdi_referenci(tmp_path)
    assert "--reference" in str(e.value)


# ---------------------------------------------------------------- porovnej

def test_porovnej_zapise_vystupy(tmp_path, sources):
    beh, _ = _dokonceny_beh(tmp_path, sources)
    hod = _hodnotitel()
    html = porovnej(beh, sources, REFERENCE, hod, print).read_text(encoding="utf-8")
    assert "Kalibrace" in html and (beh.directory / "porovnani_formular.md").exists()
    assert [krok for krok, *_ in hod.calls] == KROKY
    assert 'href="porovnani_formular.md"' in html

    v = ComparisonResult.model_validate_json(
        (beh.directory / "data" / "porovnani.json").read_text(encoding="utf-8"))
    assert v.generated_score == beh.state.scores["1"]
    assert v.reference_score.total == 9.2   # 0,5·9 + 0,35·9 + 0,15·10
    assert set(v.comparison.values()) == {'generated'}
    assert list(v.comparison) == [x.id for x in make_criteria(3)]
    assert len(v.rationales["B1"]) == 2
    assert [p.id for p in v.elements] == ["P1", "P2", "P3"]
    assert [p.status for p in v.coverage] == ['present', 'missing', 'partial']


def test_formular_obsahuje_otazky_z_designu(tmp_path, sources):
    beh, _ = _dokonceny_beh(tmp_path, sources)
    porovnej(beh, sources, REFERENCE, _hodnotitel(), _ticho)
    formular = (beh.directory / "porovnani_formular.md").read_text(encoding="utf-8")
    assert OTAZKY_FORMULARE == (
        "Odeslal bych to po doplnění placeholderů?",
        "Kolik minut práce do odeslatelné verze?",
        "Věcné chyby?",
        "Co chybí?",
        "Co je lepší než v referenci?",
    )
    for otazka in OTAZKY_FORMULARE:
        assert otazka in formular
    assert formular.count("Odpověď:") == len(OTAZKY_FORMULARE)


def test_poradi_dokumentu_se_prohodi(tmp_path, sources):
    beh, _ = _dokonceny_beh(tmp_path, sources)
    generovana = beh.text('draft_1')
    hod = _hodnotitel()
    porovnej(beh, sources, REFERENCE, hod, _ticho)
    zadani = {krok: z for krok, _, z in hod.calls}
    z1, z2 = zadani['comparison_pair_1'], zadani['comparison_pair_2']
    assert z1.index(generovana) < z1.index(ZNACKA)
    assert z2.index(ZNACKA) < z2.index(generovana)
    instrukce = {krok: i for krok, i, _ in hod.calls}
    # Dokumenty jsou jen A/B: nic v promptu neprozrazuje, který je generovaný a který referenční.
    for text in (z1.replace(ZNACKA, ""), z2.replace(ZNACKA, "")):
        assert "referen" not in text.lower() and "generovan" not in text.lower()
    assert "referenční" not in instrukce['comparison_pair_1'].lower()
    assert "generovan" not in instrukce['comparison_pair_1'].lower()
    assert instrukce['comparison_pair_1'] == instrukce['comparison_pair_2']


def test_kalibrace_hodnoti_referenci_stejnymi_kriterii(tmp_path, sources):
    beh, _ = _dokonceny_beh(tmp_path, sources)
    hod = _hodnotitel()
    porovnej(beh, sources, REFERENCE, hod, _ticho)
    krok, instrukce, zadani = hod.calls[0]
    assert ZNACKA in zadani and "**N1**" in instrukce and "**B1**" in instrukce
    assert TEST_REQUEST.strip() in instrukce
    # Prvky se vytahují z reference, pokrytí se ověřuje v generované nabídce.
    zadani_kroku = {krok: z for krok, _, z in hod.calls}
    assert ZNACKA in zadani_kroku['comparison_elements']
    assert ZNACKA not in zadani_kroku['comparison_coverage']
    assert beh.text('draft_1') in zadani_kroku['comparison_coverage']
    assert "**P2** Kritéria převzetí po etapách" in zadani_kroku['comparison_coverage']


def test_pisatel_nikdy_nevidi_referenci(tmp_path, sources):
    beh, pisatel = _dokonceny_beh(tmp_path, sources)
    hod = _hodnotitel()
    porovnej(beh, sources, REFERENCE, hod, _ticho)
    assert pisatel.calls, "pisatel měl během běhu pracovat"
    for _, instrukce, zadani in pisatel.calls:
        assert ZNACKA not in instrukce and ZNACKA not in zadani
    assert any(ZNACKA in z for _, _, z in hod.calls)


def test_porovnani_nedokonceneho_behu(tmp_path, sources):
    beh = make_run(tmp_path, sources)
    hod = _hodnotitel()
    with pytest.raises(InputError):
        porovnej(beh, sources, REFERENCE, hod, _ticho)
    assert hod.calls == []


def test_porovnani_neprepise_stav_behu_a_ulozi_spotrebu(tmp_path, sources):
    beh, _ = _dokonceny_beh(tmp_path, sources)
    pred = Run.open(beh.directory).state
    porovnej(beh, sources, REFERENCE, _hodnotitel(), _ticho)
    po = Run.open(beh.directory).state
    assert po.status == 'completed' and po.ended_at == pred.ended_at
    assert po.steps == pred.steps and po.scores == pred.scores
    assert po.final_version == pred.final_version and po.stop_reason == pred.stop_reason
    assert [s.step for s in po.usage[len(pred.usage):]] == KROKY


def test_opakovane_porovnani_prepise_vystupy(tmp_path, sources):
    beh, _ = _dokonceny_beh(tmp_path, sources)
    porovnej(beh, sources, REFERENCE, _hodnotitel(), _ticho)
    soubory = sorted(p.name for p in beh.directory.iterdir())
    formular = beh.directory / "porovnani_formular.md"
    formular.write_text(formular.read_text(encoding="utf-8").replace(
        "Odpověď:", "Odpověď: ano, 30 minut", 1), encoding="utf-8")

    hod = _hodnotitel(comparison_coverage=[_pokryti(('present', "A"), ('present', "B"), ('present', "C"))])
    porovnej(beh, sources, REFERENCE, hod, _ticho)

    assert sorted(p.name for p in beh.directory.iterdir()) == soubory
    assert "Odpověď: ano, 30 minut" in formular.read_text(encoding="utf-8")
    v = ComparisonResult.model_validate_json(
        (beh.directory / "data" / "porovnani.json").read_text(encoding="utf-8"))
    assert [p.status for p in v.coverage] == ['present', 'present', 'present']
    assert len([s for s in Run.open(beh.directory).state.usage if s.step.startswith("comparison_")]) == 10


def test_html_escapuje_vystup_modelu(tmp_path, sources):
    beh, _ = _dokonceny_beh(tmp_path, sources)
    ids = [x.id for x in make_criteria(3)]
    kal = make_evaluation(9.0, suggestions=0)
    kal.criteria[0].rationale = "<script>alert(0)</script>"
    hod = _hodnotitel(
        comparison_calibration=[kal],
        comparison_pair_1=[PairComparison(criteria=[k(i, "A", "<script>alert(1)</script>") for i in ids])],
        comparison_elements=[_prvky("<script>alert(2)</script>", "<b>tučně</b>", "Definice vady")],
        comparison_coverage=[_pokryti(('present', "<script>alert(3)</script>"), ('missing', "x"), ('present', "y"))],
    )
    html = porovnej(beh, sources, REFERENCE, hod, _ticho).read_text(encoding="utf-8")
    assert "<script" not in html and "<b>tučně</b>" not in html
    for n in range(4):
        assert f"&lt;script&gt;alert({n})" in html


def test_pokryti_chybejici_prvni(tmp_path, sources):
    beh, _ = _dokonceny_beh(tmp_path, sources)
    hod = _hodnotitel(
        comparison_elements=[_prvky("PRVEK-JE", "PRVEK-CASTECNE", "PRVEK-CHYBI")],
        comparison_coverage=[_pokryti(('present', "k1"), ('partial', "k2"), ('missing', "k3"))],
    )
    html = porovnej(beh, sources, REFERENCE, hod, _ticho).read_text(encoding="utf-8")
    assert html.index("PRVEK-CHYBI") < html.index("PRVEK-CASTECNE") < html.index("PRVEK-JE")


@pytest.mark.parametrize("skore, ocekavano", [(9.5, "Reference dosáhla cílového skóre"),
                                              (7.5, "Reference nedosáhla cílového skóre")])
def test_kalibrace_veta_o_cilovem_skore(tmp_path, sources, skore, ocekavano):
    beh, _ = _dokonceny_beh(tmp_path, sources)
    hod = _hodnotitel(comparison_calibration=[make_evaluation(skore, suggestions=0)])
    html = porovnej(beh, sources, REFERENCE, hod, _ticho).read_text(encoding="utf-8")
    assert ocekavano in html


# ---------------------------------------------------------------- validace a oprava

def test_srovnani_s_chybejicim_kriteriem_se_opravi(tmp_path, sources):
    beh, _ = _dokonceny_beh(tmp_path, sources)
    ids = [x.id for x in make_criteria(3)]
    neuplne = PairComparison(criteria=[k(i, "A") for i in ids[1:]] + [k("X9", "A")])
    uplne = PairComparison(criteria=[k(i, "A") for i in ids])
    hod = _hodnotitel(comparison_pair_1=[neuplne, uplne])
    porovnej(beh, sources, REFERENCE, hod, _ticho)
    volani = [(krok, z) for krok, _, z in hod.calls if krok == 'comparison_pair_1']
    assert len(volani) == 2
    assert "## Oprava" in volani[1][1] and "N1" in volani[1][1] and "X9" in volani[1][1]


def test_srovnani_s_duplicitou_po_oprave_je_chyba_a_spotreba_zustane(tmp_path, sources):
    beh, _ = _dokonceny_beh(tmp_path, sources)
    ids = [x.id for x in make_criteria(3)]
    duplicitni = PairComparison(criteria=[k(i, "A") for i in ids] + [k("N1", "B")])
    hod = _hodnotitel(comparison_pair_2=[duplicitni, duplicitni])
    with pytest.raises(ModelError) as e:
        porovnej(beh, sources, REFERENCE, hod, _ticho)
    assert e.value.kind == 'invalid_output' and "N1" in e.value.detail
    spotreba = [s.step for s in Run.open(beh.directory).state.usage if s.step.startswith("comparison_")]
    assert spotreba == KROKY[:2] + ['comparison_pair_2'] * 2
    assert not (beh.directory / "porovnani.html").exists()


def test_pokryti_musi_pokryt_kazdy_prvek(tmp_path, sources):
    beh, _ = _dokonceny_beh(tmp_path, sources)
    neuplne = Coverage(items=[ElementCoverage(id="P1", status='present', comment="x")])
    hod = _hodnotitel(comparison_coverage=[neuplne, _pokryti(('present', "a"), ('present', "b"), ('present', "c"))])
    porovnej(beh, sources, REFERENCE, hod, _ticho)
    oprava = [z for krok, _, z in hod.calls if krok == 'comparison_coverage'][1]
    assert "## Oprava" in oprava and "P2" in oprava and "P3" in oprava


@pytest.mark.parametrize('prvky', [ReferenceElements(elements=[]),
                                   ReferenceElements(elements=[ReferenceElement(id="P1", description="a"),
                                                      ReferenceElement(id="P1", description="b")])])
def test_prvky_prazdne_nebo_duplicitni_se_opravi(tmp_path, sources, prvky):
    beh, _ = _dokonceny_beh(tmp_path, sources)
    hod = _hodnotitel(comparison_elements=[prvky, _prvky("a", "b", "c")])
    porovnej(beh, sources, REFERENCE, hod, _ticho)
    assert [krok for krok, *_ in hod.calls].count('comparison_elements') == 2


# ---------------------------------------------------------------- příkazová řádka

@pytest.fixture
def koren(tmp_path, repo_root) -> Path:
    """Kořen aplikace v tmp: konfigurace, prompty, input/poptavka.md a examples/ s referencí."""
    kor = tmp_path / "app"
    kor.mkdir()
    shutil.copy(repo_root / "settings.yaml", kor / "settings.yaml")
    shutil.copytree(repo_root / "profiles", kor / "profiles")
    shutil.copytree(repo_root / 'prompts', kor / 'prompts')
    (kor / "input").mkdir()
    (kor / "input" / "poptavka.md").write_text(TEST_REQUEST, encoding="utf-8")
    (kor / "examples").mkdir()
    (kor / "examples" / "reference.md").write_text(REFERENCE, encoding="utf-8")
    return kor


def _dokonceny_beh_cli(koren: Path, nanecisto: bool = False) -> tuple[Path, FakeModel]:
    """Dokončený běh s falešnými modely; examples/ s referencí už existuje.

    Výchozí je ostrý běh (porovnat ukázkový běh odmítá): klíče se nastaví jen na dobu běhu,
    aby testy porovnání mohly ověřit, které klíče porovnání vyžaduje.
    """
    modely = demo_models()
    argv = ["--nanecisto"] if nanecisto else []
    pred = set((koren / "output").iterdir()) if (koren / "output").exists() else set()
    if not nanecisto:
        os.environ["ANTHROPIC_API_KEY"] = os.environ["OPENAI_API_KEY"] = "test-klic"
    try:
        assert main(argv, koren=koren, vstup_fn=lambda _: "1", vystup=io.StringIO(),
                    tovarna_modelu=lambda konf, n: modely) == 0
    finally:
        if not nanecisto:
            os.environ.pop("ANTHROPIC_API_KEY", None)
            os.environ.pop("OPENAI_API_KEY", None)
    (slozka,) = set((koren / "output").iterdir()) - pred
    return slozka, modely[0]


def test_cli_porovnat_ukazkovy_beh_odmitne(koren, monkeypatch):
    slozka, _ = _dokonceny_beh_cli(koren, nanecisto=True)
    assert Run.open(slozka).state.dry_run
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    hod = _hodnotitel()
    out = io.StringIO()
    assert main(["porovnat", slozka.name], koren=koren, vystup=out,
                tovarna_modelu=lambda konf, n: (FakeModel({}), hod)) == 2
    assert "ukázkový" in out.getvalue() and hod.calls == []
    assert not (slozka / "porovnani.html").exists()


def test_cli_porovnat_bez_slozky_preskoci_ukazkove_behy(koren, monkeypatch):
    ostry, _ = _dokonceny_beh_cli(koren)
    ukazkovy, _ = _dokonceny_beh_cli(koren, nanecisto=True)   # novější
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    assert main(["porovnat"], koren=koren, vystup=io.StringIO(),
                tovarna_modelu=lambda konf, n: (FakeModel({}), _hodnotitel())) == 0
    assert (ostry / "porovnani.html").exists() and not (ukazkovy / "porovnani.html").exists()


def test_cli_porovnat_jen_ukazkove_behy_je_kod_2(koren, monkeypatch):
    _dokonceny_beh_cli(koren, nanecisto=True)
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    out = io.StringIO()
    assert main(["porovnat"], koren=koren, vystup=out,
                tovarna_modelu=lambda konf, n: (FakeModel({}), _hodnotitel())) == 2
    assert "ukázkové" in out.getvalue()


def test_cli_porovnat_bez_slozky(koren, monkeypatch):
    slozka, pisatel_behu = _dokonceny_beh_cli(koren)
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    pisatel, hod = FakeModel({}, name="claude-falesny"), _hodnotitel()
    out = io.StringIO()
    assert main(["porovnat"], koren=koren, vystup=out,
                tovarna_modelu=lambda konf, nanecisto: (pisatel, hod)) == 0
    assert (slozka / "porovnani.html").exists()
    assert [krok for krok, *_ in hod.calls] == KROKY
    assert any(ZNACKA in z for _, _, z in hod.calls)
    # Generování nikdy nečte examples/ – pisatel referenci neviděl ani během běhu.
    assert pisatel.calls == []
    for _, instrukce, zadani in pisatel_behu.calls:
        assert ZNACKA not in instrukce and ZNACKA not in zadani
    assert "porovnani.html" in out.getvalue()


def test_cli_porovnat_jen_s_klicem_openai(koren, monkeypatch):
    _dokonceny_beh_cli(koren)
    nastaveni = koren / "settings.yaml"   # klíče se kontrolují jen v režimu api
    nastaveni.write_text(nastaveni.read_text(encoding="utf-8").replace("mode: subscription", "mode: api"),
                         encoding="utf-8")
    out = io.StringIO()
    assert main(["porovnat"], koren=koren, vystup=out) == 2
    assert "OPENAI_API_KEY" in out.getvalue() and "ANTHROPIC_API_KEY" not in out.getvalue()


def test_cli_porovnat_se_slozkou_a_referenci(koren, monkeypatch, tmp_path):
    slozka, _ = _dokonceny_beh_cli(koren)
    (koren / "examples" / "druha.md").write_text("# Druhá", encoding="utf-8")   # examples/ nejednoznačné
    jina = tmp_path / "jina_reference.md"
    jina.write_text("# Jiná reference JINA-ZNACKA", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    hod = _hodnotitel()
    assert main(["porovnat", slozka.name, "--reference", str(jina)], koren=koren, vystup=io.StringIO(),
                tovarna_modelu=lambda konf, nanecisto: (FakeModel({}), hod)) == 0
    assert "JINA-ZNACKA" in hod.calls[0][2]


def test_cli_porovnat_nejednoznacna_reference(koren, monkeypatch):
    _dokonceny_beh_cli(koren)
    (koren / "examples" / "druha.md").write_text("# Druhá", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    out = io.StringIO()
    assert main(["porovnat"], koren=koren, vystup=out,
                tovarna_modelu=lambda konf, nanecisto: (FakeModel({}), _hodnotitel())) == 2
    assert "--reference" in out.getvalue()


def test_cli_porovnat_neexistujici_reference(koren, monkeypatch):
    _dokonceny_beh_cli(koren)
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    out = io.StringIO()
    assert main(["porovnat", "--reference", "neni.docx"], koren=koren, vystup=out,
                tovarna_modelu=lambda konf, nanecisto: (FakeModel({}), _hodnotitel())) == 2
    assert "neni.docx" in out.getvalue()


def test_cli_porovnat_bez_dokonceneho_behu(koren, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    out = io.StringIO()
    assert main(["porovnat"], koren=koren, vystup=out,
                tovarna_modelu=lambda konf, nanecisto: (FakeModel({}), _hodnotitel())) == 2
    assert "dokončený" in out.getvalue()


def test_cli_porovnat_nedokonceny_beh_se_slozkou(koren, monkeypatch):
    assert main(["--nanecisto"], koren=koren, vstup_fn=lambda _: "1", vystup=io.StringIO(),
                tovarna_modelu=lambda konf, nanecisto: (
                    demo_models()[0], FakeModel({'evaluation_1': [ModelError('network', "OpenAI")]}))) == 1
    slozka = next((koren / "output").iterdir())
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    out = io.StringIO()
    assert main(["porovnat", str(slozka)], koren=koren, vystup=out,
                tovarna_modelu=lambda konf, nanecisto: (FakeModel({}), _hodnotitel())) == 2
    assert "dokončen" in out.getvalue()


def test_cli_porovnat_chyba_modelu_je_kod_1(koren, monkeypatch):
    slozka, _ = _dokonceny_beh_cli(koren)
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    hod = _hodnotitel(comparison_elements=[ModelError('overloaded', "OpenAI")])
    out = io.StringIO()
    assert main(["porovnat"], koren=koren, vystup=out,
                tovarna_modelu=lambda konf, nanecisto: (FakeModel({}), hod)) == 1
    assert "porovnat.bat" in out.getvalue() and "pokracovat.bat" not in out.getvalue()
    stav = Run.open(slozka).state
    assert stav.status == 'completed'
    assert [s.step for s in stav.usage if s.step.startswith("comparison_")] == KROKY[:3]
    assert "Chyba modelu při porovnání" in (slozka / "data" / "beh.log").read_text(encoding="utf-8")


def test_cli_porovnat_ulozi_surovou_odpoved(koren, monkeypatch):
    slozka, _ = _dokonceny_beh_cli(koren)
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    chyba = ModelError('invalid_output', "OpenAI", detail="x", raw_response="SUROVA-ODPOVED")
    hod = _hodnotitel(comparison_calibration=[chyba, chyba])   # neplatná i po opravě
    assert main(["porovnat"], koren=koren, vystup=io.StringIO(),
                tovarna_modelu=lambda konf, nanecisto: (FakeModel({}), hod)) == 1
    surove = list((slozka / "data").glob("surova_odpoved_porovnani_*.txt"))
    assert len(surove) == 1 and surove[0].read_text(encoding="utf-8") == "SUROVA-ODPOVED"


def test_cli_porovnat_doplni_prompty_porovnani_do_kopie_behu(koren, monkeypatch):
    """Běh založený před přidáním porovnání nemá prompty porovnání ve své kopii konfigurace."""
    slozka, _ = _dokonceny_beh_cli(koren)
    kopie = slozka / "data" / "konfigurace" / "prompty"
    for p in kopie.glob("porovnani_*.md"):
        p.unlink()
    (koren / "prompts" / "comparison_elements.md").write_text(
        (koren / "prompts" / "comparison_elements.md").read_text(encoding="utf-8") + "\nUPRAVENY-PROMPT\n",
        encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    hod = _hodnotitel()
    assert main(["porovnat"], koren=koren, vystup=io.StringIO(),
                tovarna_modelu=lambda konf, nanecisto: (FakeModel({}), hod)) == 0
    assert "UPRAVENY-PROMPT" in dict((krok, i) for krok, i, _ in hod.calls)['comparison_elements']
    assert "UPRAVENY-PROMPT" in (kopie / "porovnani_prvky.md").read_text(encoding="utf-8")
    # Kalibrace hodnotí stejným promptem jako běh (kopie hodnoceni.md se nepřepisuje).
    (koren / "prompts" / "evaluation.md").write_text("ZMENENY", encoding="utf-8")
    hod = _hodnotitel()
    assert main(["porovnat"], koren=koren, vystup=io.StringIO(),
                tovarna_modelu=lambda konf, nanecisto: (FakeModel({}), hod)) == 0
    assert "ZMENENY" not in hod.calls[0][1]


def test_cli_porovnat_nanecisto_neni_podporovano(koren):
    _dokonceny_beh_cli(koren)
    out = io.StringIO()
    assert main(["--nanecisto", "porovnat"], koren=koren, vystup=out) == 2
    assert "--nanecisto" in out.getvalue()


def test_kalibrace_v_html_ukazuje_skore_po_kriteriich(tmp_path, sources):
    beh, _ = _dokonceny_beh(tmp_path, sources)
    kal = make_evaluation(7.0, suggestions=0)
    html = porovnej(beh, sources, REFERENCE, _hodnotitel(comparison_calibration=[kal]), _ticho) \
        .read_text(encoding="utf-8")
    finalni = beh.data('evaluation_1', Evaluation)
    assert finalni.criteria[0].score == 9.5
    assert "9,5" in html and "7,0" in html

import shutil
from datetime import datetime
from pathlib import Path

import pytest

import refiner.aplikace as aplikace
from refiner.aplikace import dokonci, najdi_posledni_beh, obnov_beh, otevri_dokonceny, zahaj_beh
from refiner.run import Run
from refiner.models.errors import ModelError
from refiner.models.fakes import FakeModel
from refiner.input import InputError
from tests.helpers import TEST_REQUEST, make_evaluation, scripted_responses, scripted_models

T = datetime(2026, 10, 17, 9, 0)


@pytest.fixture
def koren(tmp_path, repo_root) -> Path:
    """Kořen aplikace v tmp: kopie settings.yaml, profiles/, prompty/ a input/poptavka.md."""
    k = tmp_path / "app"
    k.mkdir()
    shutil.copy(repo_root / "settings.yaml", k / "settings.yaml")
    shutil.copytree(repo_root / "profiles", k / "profiles")
    shutil.copytree(repo_root / 'prompts', k / 'prompts')
    (k / "input").mkdir()
    (k / "input" / "poptavka.md").write_text(TEST_REQUEST, encoding="utf-8")
    return k


def _zahaj(koren: Path, ted: datetime = T):
    return zahaj_beh(koren, koren / "input" / "poptavka.md", "nabidka", ted)


# ---------------------------------------------------------------- zahájení a obnovení

def test_zahaj_beh_zkopiruje_konfiguraci_a_vstup(koren):
    (koren / 'materials').mkdir()
    (koren / 'materials' / "profil_firmy.md").write_text("Firma Alfa s.r.o.", encoding="utf-8")
    (koren / "input" / "poptavka.kriteria.yaml").write_text("vahy: {B1: 2}\n", encoding="utf-8")

    beh, z = _zahaj(koren)

    assert beh.directory.parent == koren / "output"
    assert (beh.directory / "01_poptavka.md").exists()
    assert (beh.directory / "01_poptavka.md").read_text(encoding="utf-8") == TEST_REQUEST
    konf = beh.directory / "data" / "konfigurace"
    assert (konf / "prompty" / "navrh.md").exists()
    assert (konf / "nastaveni.yaml").exists()
    assert (konf / "profil.yaml").read_text(encoding="utf-8") == \
        (koren / "profiles" / "proposal.yaml").read_text(encoding="utf-8")
    assert (konf / "kriteria.yaml").exists()
    assert z.prompts == beh.directory / "data" / "konfigurace" / "prompty"
    assert z.request == TEST_REQUEST
    assert "Firma Alfa s.r.o." in z.materials
    assert "Firma Alfa s.r.o." in (beh.directory / "data" / "podklady.md").read_text(encoding="utf-8")
    assert z.configuration.profile_id == "proposal"
    assert {k.id: k.weight for k in z.configuration.profile_criteria}["B1"] == 2
    assert beh.state.output_profile_name == "nabidka" and beh.state.input == "poptavka.md"


def test_zahaj_beh_bez_kriterii_a_podkladu(koren):
    beh, z = _zahaj(koren)
    assert not (beh.directory / "data" / "konfigurace" / "kriteria.yaml").exists()
    assert z.materials == ""
    assert (beh.directory / "data" / "podklady.md").read_text(encoding="utf-8") == ""


def test_zahaj_beh_crlf_vstup_nezdvoji_radky(koren):
    (koren / "input" / "poptavka.md").write_bytes(b"# Popt\r\n\r\nText.\r\n")
    (koren / 'materials').mkdir()
    (koren / 'materials' / "profil.md").write_bytes(b"Firma\r\nIC\r\n")
    beh, z = _zahaj(koren)
    assert z.request == "# Popt\n\nText.\n"
    assert beh.text('request') == "# Popt\n\nText.\n"
    assert "Firma\nIC" in z.materials and "\r" not in z.materials


def test_obnoveni_pouzije_kopii_konfigurace(koren):
    beh, _ = _zahaj(koren)
    nastaveni = koren / "settings.yaml"
    nastaveni.write_text(nastaveni.read_text(encoding="utf-8").replace("max_revisions: 3", "max_revisions: 1"),
                         encoding="utf-8")
    (koren / "prompts" / "draft.md").write_text("ZMĚNĚNO", encoding="utf-8")

    beh2, z2 = obnov_beh(beh.directory)

    assert beh2.directory == beh.directory
    assert z2.configuration.settings.loop.max_revisions == 3
    assert z2.prompts == beh.directory / "data" / "konfigurace" / "prompty"
    assert (z2.prompts / "navrh.md").read_text(encoding="utf-8") != "ZMĚNĚNO"
    assert z2.configuration.profile_id == "proposal"
    assert z2.request == TEST_REQUEST
    # obnovení nepřepisuje existující kroky
    assert list(beh2.state.steps) == ['request'] and beh2.state.steps['request'].number == 1


def _uprav(soubor: Path, *nahrady: tuple[str, str]) -> None:
    text = soubor.read_text(encoding="utf-8")
    for a, b in nahrady:
        assert a in text
        text = text.replace(a, b)
    soubor.write_text(text, encoding="utf-8")


def test_obnoveni_s_korenem_bere_modely_a_ceny_z_repozitare(koren):
    beh, _ = _zahaj(koren)
    _uprav(koren / "settings.yaml",
           ("max_tokens_json: 32000", "max_tokens_json: 50000"),
           ("max_output_tokens: 64000", "max_output_tokens: 99000"),
           ("claude-opus-5-5: {input: 4.0", "claude-opus-5-5: {input: 7.0"),
           ("max_revisions: 3", "max_revisions: 1"))
    (koren / "prompts" / "draft.md").write_text("ZMĚNĚNO", encoding="utf-8")
    hlasky: list[str] = []

    _, z = obnov_beh(beh.directory, koren=koren, hlaseni=hlasky.append)

    n = z.configuration.settings
    assert n.models.claude.max_tokens_json == 50000 and n.models.gpt.max_output_tokens == 99000
    assert n.prices_usd_per_million["claude-opus-5-5"].input == 7.0
    # Smyčka, profil a prompty zůstávají z kopie běhu (reprodukovatelné skóre).
    assert n.loop.max_revisions == 3
    assert (z.prompts / "navrh.md").read_text(encoding="utf-8") != "ZMĚNĚNO"
    log = (beh.directory / "data" / "beh.log").read_text(encoding="utf-8")
    assert "models" in log and "settings.yaml" in log and "kopie" in log
    # Kopie konfigurace ve složce běhu se nemění.
    assert "max_tokens_json: 32000" in (beh.directory / "data" / "konfigurace" / "nastaveni.yaml") \
        .read_text(encoding="utf-8")


@pytest.mark.parametrize("pokazit", ["smazat", "neplatny"])
def test_obnoveni_s_vadnym_nastavenim_v_repozitari_pouzije_kopii(koren, pokazit):
    beh, _ = _zahaj(koren)
    nastaveni = koren / "settings.yaml"
    if pokazit == "smazat":
        nastaveni.unlink()
    else:
        _uprav(nastaveni, ("effort: high", "effort: hihg"))
    hlasky: list[str] = []

    _, z = obnov_beh(beh.directory, koren=koren, hlaseni=hlasky.append)

    assert z.configuration.settings.models.claude.max_tokens_json == 32000
    assert any("Varování" in h and "kopie" in h for h in hlasky)
    log = (beh.directory / "data" / "beh.log").read_text(encoding="utf-8")
    assert "WARNING" in log and "settings.yaml" in log


def test_obnoveni_rezim_musi_odpovidat(koren):
    beh, _ = _zahaj(koren)
    with pytest.raises(InputError, match="--nanecisto"):
        obnov_beh(beh.directory, nanecisto=True)
    demo, _ = zahaj_beh(koren, koren / "input" / "poptavka.md", "nabidka", T, nanecisto=True)
    assert demo.state.dry_run
    with pytest.raises(InputError, match="ukázkový"):
        obnov_beh(demo.directory, nanecisto=False)
    assert obnov_beh(demo.directory, nanecisto=True)[0].directory == demo.directory


def test_porovnani_odmitne_ukazkovy_beh(koren):
    demo, z = zahaj_beh(koren, koren / "input" / "poptavka.md", "nabidka", T, nanecisto=True)
    assert dokonci(demo, z, *scripted_models([9.5]), hlaseni=lambda _: None, sablona=None) == 0
    with pytest.raises(InputError, match="ukázkový"):
        otevri_dokonceny(demo.directory, nanecisto=False)


def test_obnoveni_dokonceneho_behu_odmitne(koren):
    beh, z = _zahaj(koren)
    assert dokonci(beh, z, *scripted_models([9.5]), hlaseni=lambda _: None, sablona=None) == 0
    with pytest.raises(InputError, match="je už dokončený"):
        obnov_beh(beh.directory)


def test_obnoveni_slozky_ktera_neni_beh(tmp_path):
    with pytest.raises(InputError):
        obnov_beh(tmp_path)


# ---------------------------------------------------------------- dokončení

def test_dokonci_uspech(koren):
    beh, z = _zahaj(koren)
    out: list[str] = []
    assert dokonci(beh, z, *scripted_models([9.5]), hlaseni=out.append, sablona=None) == 0
    assert (beh.directory / "FINALNI_nabidka.docx").exists() and (beh.directory / "prehled.html").exists()
    assert (beh.directory / "FINALNI_nabidka.md").read_text(encoding="utf-8") == \
        (beh.directory / "03_navrh_v1.md").read_text(encoding="utf-8")
    st = Run.open(beh.directory).state
    assert st.status == 'completed' and st.stop_reason == 'target_reached' and st.final_version == 1
    assert st.error is None
    assert any(str(beh.directory / "prehled.html") in r for r in out)


def test_chyba_api_ulozi_rozpracovany_beh(koren):
    beh, z = _zahaj(koren)
    pisatel, _ = scripted_models([9.5])
    hodnotitel = FakeModel({'evaluation_1': [ModelError('credit', "OpenAI")]}, name="gpt-falesny")
    out: list[str] = []
    assert dokonci(beh, z, pisatel, hodnotitel, hlaseni=out.append, sablona=None) == 1
    st = Run.open(beh.directory).state
    assert st.status == 'interrupted' and "kredit" in st.error and (beh.directory / "03_navrh_v1.md").exists()
    vypis = "\n".join(out)
    assert "pokracovat.bat" in vypis and (beh.directory / "prehled.html").exists()
    assert "Došel kredit u OpenAI" in vypis and str(beh.directory) in vypis
    assert "Běh byl přerušen" in (beh.directory / "prehled.html").read_text(encoding="utf-8")
    assert "ModelError" in (beh.directory / "data" / "beh.log").read_text(encoding="utf-8")


def test_surova_odpoved_se_ulozi(koren):
    beh, z = _zahaj(koren)
    pisatel, _ = scripted_models([9.5])
    # nevalidní výstup kroky jednou opraví; až druhé selhání ukončí krok
    chyba = ModelError('invalid_output', "OpenAI", raw_response="{rozbite")
    hodnotitel = FakeModel({'evaluation_1': [chyba, chyba]}, name="gpt-falesny")
    assert dokonci(beh, z, pisatel, hodnotitel, hlaseni=lambda _: None, sablona=None) == 1
    soubory = list((beh.directory / "data").glob("surova_odpoved_*.txt"))
    assert len(soubory) == 1
    assert soubory[0].read_text(encoding="utf-8") == "{rozbite"


def test_spotreba_neplatne_odpovedi_se_ulozi(koren):
    # Hodnotitel 2× odpoví (spotřeba vznikne), ale skóre 9,8 neprojde kontrolou → ModelError.
    beh, z = _zahaj(koren)
    pisatel, _ = scripted_models([9.5])
    spatne = make_evaluation(8.0, overrides={"B1": 9.8})
    hodnotitel = FakeModel({'evaluation_1': [spatne, spatne]}, name="gpt-falesny")
    assert dokonci(beh, z, pisatel, hodnotitel, hlaseni=lambda _: None, sablona=None) == 1
    st = Run.open(beh.directory).state
    assert [s.step for s in st.usage if s.model == "gpt-falesny"] == ['evaluation_1', 'evaluation_1']
    assert len((list((beh.directory / "data").glob("surova_odpoved_*.txt")))) == 1


def test_ctrl_c_ulozi_prerusen_beh(koren):
    beh, z = _zahaj(koren)
    odp_p, odp_h = scripted_responses([9.5])
    odp_p['draft_1'] = [KeyboardInterrupt(), *odp_p['draft_1']]
    pisatel = FakeModel(odp_p, name="claude-falesny")
    hodnotitel = FakeModel(odp_h, name="gpt-falesny")
    out: list[str] = []

    assert dokonci(beh, z, pisatel, hodnotitel, hlaseni=out.append, sablona=None) == 1
    st = Run.open(beh.directory).state
    assert st.status == 'interrupted' and "Ctrl+C" in st.error
    assert "pokracovat.bat" in "\n".join(out)
    assert (beh.directory / "02_nalezitosti.md").exists() and not (beh.directory / "03_navrh_v1.md").exists()

    beh2, z2 = obnov_beh(beh.directory)
    assert dokonci(beh2, z2, pisatel, hodnotitel, hlaseni=out.append, sablona=None) == 0
    st = Run.open(beh.directory).state
    assert st.status == 'completed' and st.error is None
    assert (beh.directory / "03_navrh_v1.md").exists() and (beh.directory / "FINALNI_nabidka.docx").exists()
    assert [k for k, v in st.steps.items() if v.number == 2] == ['requirements']


def test_neocekavana_vyjimka(koren):
    beh, z = _zahaj(koren)
    pisatel = FakeModel({'requirements': [ZeroDivisionError("deleni nulou")]}, name="claude-falesny")
    _, hodnotitel = scripted_models([9.5])
    out: list[str] = []
    assert dokonci(beh, z, pisatel, hodnotitel, hlaseni=out.append, sablona=None) == 1
    st = Run.open(beh.directory).state
    assert st.status == 'interrupted' and "Neočekávaná chyba" in st.error
    assert "Neočekávaná chyba" in "\n".join(out)
    log = (beh.directory / "data" / "beh.log").read_text(encoding="utf-8")
    assert "Traceback" in log and "ZeroDivisionError" in log


def test_selhani_prehledu_neprebije_puvodni_chybu(koren, monkeypatch):
    def rozbity(*_a, **_k):
        raise RuntimeError("šablona přehledu je rozbitá")

    monkeypatch.setattr(aplikace, "vytvor_prehled", rozbity)
    beh, z = _zahaj(koren)
    pisatel, _ = scripted_models([9.5])
    hodnotitel = FakeModel({'evaluation_1': [ModelError('credit', "OpenAI")]}, name="gpt-falesny")
    out: list[str] = []
    assert dokonci(beh, z, pisatel, hodnotitel, hlaseni=out.append, sablona=None) == 1
    st = Run.open(beh.directory).state
    assert st.status == 'interrupted' and "kredit" in st.error
    assert "Došel kredit" in "\n".join(out)
    assert "šablona přehledu je rozbitá" in (beh.directory / "data" / "beh.log").read_text(encoding="utf-8")


def test_selhani_docx_exportu_je_varovani(koren, monkeypatch):
    def rozbity(*_a, **_k):
        raise OSError("pandoc nenalezen")

    monkeypatch.setattr(aplikace, "exportuj_docx", rozbity)
    beh, z = _zahaj(koren)
    assert dokonci(beh, z, *scripted_models([9.5]), hlaseni=lambda _: None, sablona=None) == 0
    st = Run.open(beh.directory).state
    assert st.status == 'completed'
    assert any("DOCX" in v and "pandoc nenalezen" in v for v in st.warnings)
    assert (beh.directory / "FINALNI_nabidka.md").exists()
    assert not (beh.directory / "FINALNI_nabidka.docx").exists()


def test_log_handler_se_po_dokonceni_odpoji(koren):
    import logging

    beh, z = _zahaj(koren)
    pred = list(logging.getLogger("refiner").handlers)
    dokonci(beh, z, *scripted_models([9.5]), hlaseni=lambda _: None, sablona=None)
    assert logging.getLogger("refiner").handlers == pred
    # soubor je uzavřený – jde smazat i na Windows
    (beh.directory / "data" / "beh.log").unlink()


# ---------------------------------------------------------------- hledání posledního běhu

def test_najdi_posledni_preruseny(koren):
    output = koren / "output"
    assert najdi_posledni_beh(output, {'interrupted', 'running'}) is None

    stary, _ = _zahaj(koren, datetime(2026, 10, 17, 8, 0))
    stary.finish('interrupted', error="x")
    new, _ = _zahaj(koren, datetime(2026, 10, 17, 10, 0))
    new.finish('interrupted', error="x")
    hotovy, _ = _zahaj(koren, datetime(2026, 10, 17, 11, 0))
    hotovy.finish('completed', 'target_reached', final_version=1)
    (output / "nahodna_slozka").mkdir()
    (output / "rozbity").mkdir()
    (output / "rozbity" / "data").mkdir()
    (output / "rozbity" / "data" / "beh.json").write_text("{", encoding="utf-8")

    assert najdi_posledni_beh(output, {'interrupted', 'running'}) == new.directory
    assert najdi_posledni_beh(output, {'completed'}) == hotovy.directory
    assert najdi_posledni_beh(output, {'running'}) is None


def test_najdi_posledni_beh_preskoci_jiny_rezim(koren):
    output = koren / "output"
    ostry, _ = _zahaj(koren, datetime(2026, 10, 17, 8, 0))
    ostry.finish('interrupted', error="x")
    demo, _ = zahaj_beh(koren, koren / "input" / "poptavka.md", "nabidka",
                        datetime(2026, 10, 17, 10, 0), nanecisto=True)
    demo.finish('interrupted', error="x")
    assert najdi_posledni_beh(output, {'interrupted'}) == demo.directory
    assert najdi_posledni_beh(output, {'interrupted'}, nanecisto=False) == ostry.directory
    assert najdi_posledni_beh(output, {'interrupted'}, nanecisto=True) == demo.directory

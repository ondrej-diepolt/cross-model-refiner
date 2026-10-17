import io
import os
import shutil
from pathlib import Path

import pytest

from refiner.beh import Beh
from refiner.cli import main
from refiner.kroky import extrahuj_nalezitosti
from refiner.modely.chyby import ChybaModelu
from refiner.modely.falesne import FalesnyModel, demo_modely
from tests.pomocne import POPTAVKA_TEST


@pytest.fixture
def koren(tmp_path, koren_repa) -> Path:
    """Kořen aplikace v tmp (bez .env): nastaveni.yaml, profily/, prompty/ a input/poptavka.md."""
    k = tmp_path / "app"
    k.mkdir()
    shutil.copy(koren_repa / "nastaveni.yaml", k / "nastaveni.yaml")
    shutil.copytree(koren_repa / "profily", k / "profily")
    shutil.copytree(koren_repa / "prompty", k / "prompty")
    (k / "input").mkdir()
    (k / "input" / "poptavka.md").write_text(POPTAVKA_TEST, encoding="utf-8")
    return k


def _odpovedi(*hodnoty: str):
    fronta = list(hodnoty)
    return lambda _: fronta.pop(0)


def _jediny_beh(koren: Path) -> Beh:
    slozky = list((koren / "output").iterdir())
    assert len(slozky) == 1
    return Beh.otevri(slozky[0])


def _nepouzivat(_):
    raise AssertionError("vstup_fn se neměl volat")


# ---------------------------------------------------------------- celý běh

def test_nanecisto_cely_beh(koren):
    out = io.StringIO()
    assert main(["--nanecisto"], koren=koren, vstup_fn=lambda _: "1", vystup=out) == 0
    slozka = next((koren / "output").iterdir())
    assert (slozka / "prehled.html").exists() and (slozka / "FINALNI_nabidka.docx").exists()
    assert "Hotovo. Přehled běhu:" in out.getvalue()


def test_nanecisto_projde_celou_smyckou_s_rostoucim_skore(koren):
    assert main(["--nanecisto"], koren=koren, vstup_fn=lambda _: "1", vystup=io.StringIO()) == 0
    beh = _jediny_beh(koren)
    assert beh.stav.stav == "dokoncen"
    assert [beh.stav.skore[str(k)].celkem for k in range(1, 5)] == [7.9, 8.7, 9.2, 9.6]
    assert beh.stav.duvod_ukonceni == "cil_splnen"
    posouzeni = (beh.slozka / "05_posouzeni_1.md").read_text(encoding="utf-8")
    assert "odmít" in posouzeni.lower()
    finalni = (beh.slozka / "FINALNI_nabidka.md").read_text(encoding="utf-8")
    assert "[DOPLNIT:" in finalni


def test_nanecisto_poptavka_bez_odrazek(koren):
    (koren / "input" / "poptavka.md").write_text(
        "Poptáváme zpracování analýzy rizik.\n\nTermín dodání je do konce roku.\n", encoding="utf-8")
    assert main(["--nanecisto"], koren=koren, vstup_fn=lambda _: "1", vystup=io.StringIO()) == 0
    assert _jediny_beh(koren).stav.stav == "dokoncen"


def test_demo_modely_nalezitosti_cituji_odrazky_poptavky(zdroje):
    pisatel, hodnotitel = demo_modely()
    assert hodnotitel.nazev.startswith("gpt") and not pisatel.nazev.startswith("gpt")
    nalezitosti, varovani = extrahuj_nalezitosti(pisatel, zdroje)
    assert varovani == []
    assert [n.citace for n in nalezitosti] == [
        "popis metodiky cvičení", "harmonogram a hlavní milníky realizace", "cenu za celé plnění"]
    assert [n.id for n in nalezitosti] == ["N1", "N2", "N3"]


def test_hlaseni_neshodi_cp1250_konzoli(koren):
    buf = io.BytesIO()
    konzole = io.TextIOWrapper(buf, encoding="cp1250", errors="strict")
    assert main(["--nanecisto"], koren=koren, vstup_fn=lambda _: "1", vystup=konzole) == 0
    assert "Hotovo" in buf.getvalue().decode("utf-8", errors="replace")


class _NeprekodovatelnyProud(io.StringIO):
    """Proud bez reconfigure, který neumí znaky mimo cp1250 (jako stará konzole)."""

    encoding = "cp1250"

    def write(self, s):
        s.encode("cp1250")
        return super().write(s)


def test_hlaseni_neshodi_proud_bez_reconfigure(koren):
    out = _NeprekodovatelnyProud()
    assert main(["--nanecisto"], koren=koren, vstup_fn=lambda _: "1", vystup=out) == 0
    assert "Hotovo" in out.getvalue()


# ---------------------------------------------------------------- chyby uživatele a konfigurace

def test_chybejici_klic(koren):
    out = io.StringIO()
    assert main([], koren=koren, vstup_fn=_nepouzivat, vystup=out) == 2
    assert "ANTHROPIC_API_KEY" in out.getvalue() and ".env.example" in out.getvalue()
    assert not (koren / "output").exists() or not any((koren / "output").iterdir())


def test_chybejici_klic_openai(koren, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-klic")
    out = io.StringIO()
    assert main([], koren=koren, vstup_fn=_nepouzivat, vystup=out) == 2
    assert "OPENAI_API_KEY" in out.getvalue() and "ANTHROPIC_API_KEY" not in out.getvalue()


def test_klic_z_env_souboru(koren):
    (koren / ".env").write_text("ANTHROPIC_API_KEY=a\nOPENAI_API_KEY=b\n", encoding="utf-8")
    pouzite = []

    def tovarna(konf, nanecisto):
        pouzite.append(nanecisto)
        return demo_modely()

    out = io.StringIO()
    try:
        assert main([], koren=koren, vstup_fn=lambda _: "1", vystup=out, tovarna_modelu=tovarna) == 0
    finally:   # load_dotenv zapsal klíče do os.environ – neprosakovat do dalších testů
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)
    assert pouzite == [False]


def test_prazdny_input(koren):
    (koren / "input" / "poptavka.md").unlink()
    out = io.StringIO()
    assert main(["--nanecisto"], koren=koren, vstup_fn=_nepouzivat, vystup=out) == 2
    assert "Ve složce input/ není žádná poptávka (DOCX, MD nebo TXT)." in out.getvalue()


def test_vyber_z_vice_souboru(koren):
    (koren / "input" / "poptavka.md").rename(koren / "input" / "a_jina.md")
    (koren / "input" / "a_jina.md").write_text("# Jiná\n\n- jiný požadavek\n", encoding="utf-8")
    (koren / "input" / "b_poptavka.md").write_text(POPTAVKA_TEST, encoding="utf-8")
    out = io.StringIO()
    # "9" je neplatná volba souboru → zopakuje se; "2" = b_poptavka.md; "1" = profil Nabídka.
    assert main(["--nanecisto"], koren=koren, vstup_fn=_odpovedi("9", "2", "1"), vystup=out) == 0
    assert _jediny_beh(koren).stav.vstup == "b_poptavka.md"
    assert "1) a_jina.md" in out.getvalue() and "2) b_poptavka.md" in out.getvalue()
    assert "Neplatná volba" in out.getvalue()


def test_vyber_profilu(koren):
    out = io.StringIO()
    assert main(["--nanecisto"], koren=koren, vstup_fn=lambda _: "2", vystup=out) == 0
    beh = _jediny_beh(koren)
    assert beh.stav.profil == "smernice"
    assert "Nabídka, nebo směrnice?" in out.getvalue()
    assert (beh.slozka / "FINALNI_smernice.docx").exists()


def test_jeden_profil_se_nepta(koren):
    (koren / "profily" / "smernice.yaml").unlink()
    assert main(["--nanecisto"], koren=koren, vstup_fn=_nepouzivat, vystup=io.StringIO()) == 0
    assert _jediny_beh(koren).stav.profil == "nabidka"


def test_konec_vstupu_pri_vyberu_je_kod_2(koren):
    def eof(_):
        raise EOFError

    out = io.StringIO()
    assert main(["--nanecisto"], koren=koren, vstup_fn=eof, vystup=out) == 2
    assert not (koren / "output").exists()


def test_chyba_konfigurace_je_kod_2(koren):
    (koren / "nastaveni.yaml").write_text("smycka: [\n", encoding="utf-8")
    out = io.StringIO()
    assert main(["--nanecisto"], koren=koren, vstup_fn=lambda _: "1", vystup=out) == 2
    assert "nastaveni.yaml" in out.getvalue()
    assert not (koren / "output").exists()


def test_prazdna_poptavka_je_kod_2(koren):
    (koren / "input" / "poptavka.md").write_text("  \n", encoding="utf-8")
    out = io.StringIO()
    assert main(["--nanecisto"], koren=koren, vstup_fn=lambda _: "1", vystup=out) == 2
    assert "neobsahuje žádný text" in out.getvalue()


# ---------------------------------------------------------------- pokračování

def _tovarna_selze_v_hodnoceni_1(konf, nanecisto):
    pisatel, _ = demo_modely()
    return pisatel, FalesnyModel({"hodnoceni_1": [ChybaModelu("sit", "OpenAI")]}, nazev="gpt-falesny")


def test_pokracovat_bez_hodnoty_najde_posledni(koren, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-klic")
    monkeypatch.setenv("OPENAI_API_KEY", "test-klic")
    out = io.StringIO()
    assert main([], koren=koren, vstup_fn=lambda _: "1", vystup=out,
                tovarna_modelu=_tovarna_selze_v_hodnoceni_1) == 1
    assert "pokracovat.bat" in out.getvalue()
    assert _jediny_beh(koren).stav.stav == "prerusen"

    modely = []

    def tovarna(konf, nanecisto):
        modely.append(demo_modely())
        return modely[-1]

    assert main(["--pokracovat"], koren=koren, vstup_fn=_nepouzivat, vystup=io.StringIO(),
                tovarna_modelu=tovarna) == 0
    beh = _jediny_beh(koren)
    assert beh.stav.stav == "dokoncen"
    pisatel = modely[0][0]
    assert "nalezitosti" not in [krok for krok, _, _ in pisatel.volani]


def test_pokracovat_se_slozkou(koren):
    assert main(["--nanecisto"], koren=koren, vstup_fn=lambda _: "1", vystup=io.StringIO(),
                tovarna_modelu=_tovarna_selze_v_hodnoceni_1) == 1
    slozka = next((koren / "output").iterdir())
    assert main(["--nanecisto", "--pokracovat", slozka.name], koren=koren, vstup_fn=_nepouzivat,
                vystup=io.StringIO()) == 0
    assert Beh.otevri(slozka).stav.stav == "dokoncen"


def test_pokracovat_bez_preruseneho_behu(koren):
    out = io.StringIO()
    assert main(["--nanecisto", "--pokracovat"], koren=koren, vstup_fn=_nepouzivat, vystup=out) == 2
    assert "output" in out.getvalue()


def test_pokracovat_dokonceny_beh_je_kod_2(koren):
    assert main(["--nanecisto"], koren=koren, vstup_fn=lambda _: "1", vystup=io.StringIO()) == 0
    slozka = next((koren / "output").iterdir())
    out = io.StringIO()
    assert main(["--nanecisto", "--pokracovat", str(slozka)], koren=koren, vstup_fn=_nepouzivat,
                vystup=out) == 2
    assert "dokončený" in out.getvalue()

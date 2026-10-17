"""Životní cyklus běhu: zahájení, obnovení, dokončení a zpracování chyb (design kap. 8 a 9)."""
from __future__ import annotations

import logging
import shutil
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from refiner.beh import SLOZKA_KONFIGURACE, Beh
from refiner.konfigurace import ChybaKonfigurace, cesta_kriterii_k_poptavce, nacti_konfiguraci
from refiner.kroky import Zdroje
from refiner.modely.chyby import ChybaModelu
from refiner.modely.rozhrani import Model
from refiner.porovnani import PROMPTY_POROVNANI, porovnej
from refiner.smycka import spust_smycku
from refiner.vstup import ChybaVstupu, nacti_jako_markdown, nacti_podklady
from refiner.vystup.docx import exportuj_docx
from refiner.vystup.prehled import vytvor_prehled

_log = logging.getLogger(__name__)

_PODKLADY = "data/podklady.md"
_STAV = "data/beh.json"
_LOG = "data/beh.log"

HLASKA_CTRL_C = "Přerušeno uživatelem (Ctrl+C)."
HLASKA_NEOCEKAVANA = "Neočekávaná chyba programu – podrobnosti v data/beh.log."
HLASKA_POKRACOVAT = "Pokračovat: pokracovat.bat"
HLASKA_POROVNAT_ZNOVU = "Stav běhu se nezměnil; porovnání zopakujete spuštěním porovnat.bat."


# ---------------------------------------------------------------- zahájení a obnovení

def _nacti_zdroje(beh: Beh) -> Zdroje:
    """Zdroje výhradně z kopií ve složce běhu (konfigurace, prompty, poptávka, podklady)."""
    konf_slozka = beh.slozka / SLOZKA_KONFIGURACE
    kriteria = konf_slozka / "kriteria.yaml"
    konfigurace = nacti_konfiguraci(
        konf_slozka / "nastaveni.yaml",
        konf_slozka / "profil.yaml",
        kriteria if kriteria.exists() else None,
    )
    # Kopie profilu se jmenuje profil.yaml; název profilu (pro FINALNI_<profil>) je ve stavu běhu.
    konfigurace = replace(konfigurace, profil_nazev=beh.stav.profil)
    podklady = beh.slozka / _PODKLADY
    return Zdroje(
        poptavka=beh.text("poptavka"),
        podklady=podklady.read_text(encoding="utf-8") if podklady.exists() else "",
        konfigurace=konfigurace,
        prompty=konf_slozka / "prompty",
    )


def zahaj_beh(koren: Path, vstup: Path, profil: str, ted: datetime) -> tuple[Beh, Zdroje]:
    """Založí běh v koren/output: kopie konfigurace a promptů, krok poptavka a data/podklady.md."""
    nastaveni = koren / "nastaveni.yaml"
    soubor_profilu = koren / "profily" / f"{profil}.yaml"
    kriteria = cesta_kriterii_k_poptavce(vstup)
    # Chyby konfigurace a vstupu se ohlásí dřív, než vznikne složka běhu.
    nacti_konfiguraci(nastaveni, soubor_profilu, kriteria)
    poptavka = nacti_jako_markdown(vstup)
    podklady = nacti_podklady(koren / "podklady")

    beh = Beh.novy(koren / "output", vstup.name, profil, ted)
    konf_slozka = beh.slozka / SLOZKA_KONFIGURACE
    konf_slozka.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(nastaveni, konf_slozka / "nastaveni.yaml")
    shutil.copyfile(soubor_profilu, konf_slozka / "profil.yaml")
    shutil.copytree(koren / "prompty", konf_slozka / "prompty")
    if kriteria is not None:
        shutil.copyfile(kriteria, konf_slozka / "kriteria.yaml")
    beh.zapis_pevny(_PODKLADY, podklady)
    beh.zapis("poptavka", "poptavka.md", poptavka)
    return beh, _nacti_zdroje(beh)


def _otevri(slozka: Path) -> Beh:
    if not (slozka / _STAV).is_file():
        raise ChybaVstupu(f"Složka {slozka} není složka běhu (chybí {_STAV}).")
    try:
        return Beh.otevri(slozka)
    except (OSError, ValidationError) as e:
        raise ChybaVstupu(f"Stav běhu ve složce {slozka} nelze přečíst ({_STAV}).") from e


def obnov_beh(slozka: Path) -> tuple[Beh, Zdroje]:
    """Otevře přerušený běh; konfiguraci, prompty i vstupy bere z kopií ve složce běhu."""
    beh = _otevri(slozka)
    if beh.stav.stav == "dokoncen":
        raise ChybaVstupu(f"Běh {slozka.name} je už dokončený.")
    if not beh.hotovo("poptavka"):
        raise ChybaVstupu(f"Běh {slozka.name} nelze obnovit: chybí uložená poptávka.")
    return beh, _nacti_zdroje(beh)


def otevri_dokonceny(slozka: Path) -> tuple[Beh, Zdroje]:
    """Otevře dokončený běh k porovnání; zdroje bere z kopií ve složce běhu."""
    beh = _otevri(slozka)
    if beh.stav.stav != "dokoncen":
        raise ChybaVstupu(f"Běh {slozka.name} není dokončený; porovnat lze jen dokončený běh.")
    return beh, _nacti_zdroje(beh)


def obnov_prompty_porovnani(beh: Beh, prompty: Path) -> None:
    """Zkopíruje aktuální prompty porovnání z `prompty` do kopie konfigurace běhu.

    Porovnání je nástroj ladění: má používat aktuální prompty porovnání (i u běhů založených
    dřív, než prompty existovaly), a kopie ve složce běhu pak ukazuje, s čím se porovnávalo.
    Ostatní prompty (hodnoceni.md pro kalibraci) zůstávají z běhu.
    """
    cil = beh.slozka / SLOZKA_KONFIGURACE / "prompty"
    for nazev in PROMPTY_POROVNANI:
        zdroj = prompty / f"{nazev}.md"
        if zdroj.is_file():
            cil.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(zdroj, cil / f"{nazev}.md")


def najdi_posledni_beh(output: Path, stavy: set[str]) -> Path | None:
    """Nejnovější (podle `vytvoreno`) složka běhu v `output` s jedním z daných stavů."""
    if not output.is_dir():
        return None
    nalezene: list[tuple[datetime, str, Path]] = []
    for slozka in output.iterdir():
        if not (slozka / _STAV).is_file():
            continue
        try:
            stav = Beh.otevri(slozka).stav
        except (OSError, ValidationError):
            continue
        if stav.stav in stavy:
            nalezene.append((stav.vytvoreno, slozka.name, slozka))
    return max(nalezene)[2] if nalezene else None


# ---------------------------------------------------------------- dokončení

def _preruseni(
    beh: Beh,
    zdroje: Zdroje,
    pisatel: Model,
    hodnotitel: Model,
    hlaseni: Callable[[str], None],
    chyba: str,
) -> int:
    """Uloží běh jako přerušený, zkusí vytvořit přehled a ohlásí, jak pokračovat. Vrací 1."""
    try:
        # Spotřeba volání, která vrátila odpověď, ale krok pak neprošel kontrolou.
        zbytek = pisatel.vyzvedni_spotrebu() + hodnotitel.vyzvedni_spotrebu()
        if zbytek:
            beh.pridej_spotrebu(zbytek)
    except Exception:
        _log.exception("Spotřebu přerušeného kroku se nepodařilo uložit.")
    beh.ukonci("prerusen", chyba=chyba)
    try:
        vytvor_prehled(beh, zdroje.konfigurace)
    except Exception:
        _log.exception("Přehled přerušeného běhu se nepodařilo vytvořit.")
    hlaseni(chyba)
    hlaseni(f"Rozpracovaný běh je uložen ve složce: {beh.slozka}")
    hlaseni(HLASKA_POKRACOVAT)
    return 1


def _dokonci(
    beh: Beh,
    zdroje: Zdroje,
    pisatel: Model,
    hodnotitel: Model,
    hlaseni: Callable[[str], None],
    sablona: Path | None,
) -> int:
    try:
        vysledek = spust_smycku(beh, zdroje, pisatel, hodnotitel, hlaseni)
        finalni = beh.text(f"navrh_{vysledek.finalni_verze}")
        nazev = zdroje.konfigurace.profil_nazev
        beh.zapis_pevny(f"FINALNI_{nazev}.md", finalni)
        try:
            exportuj_docx(finalni, beh.slozka / f"FINALNI_{nazev}.docx", sablona)
        except Exception as e:
            _log.exception("Export do DOCX selhal.")
            beh.pridej_varovani(
                f"Export do DOCX se nepodařil ({e}); finální text je v souboru FINALNI_{nazev}.md."
            )
        beh.ukonci("dokoncen", vysledek.duvod, finalni_verze=vysledek.finalni_verze)
        prehled = vytvor_prehled(beh, zdroje.konfigurace)
        _log.info("Běh dokončen (%s, finální verze %d).", vysledek.duvod, vysledek.finalni_verze)
        hlaseni(f"Hotovo. Přehled běhu: {prehled}")
        return 0
    except ChybaModelu as e:
        _log.exception("Chyba modelu: %s", e.hlaska)
        if e.surova_odpoved is not None:
            beh.zapis_pevny(f"data/surova_odpoved_{datetime.now():%Y%m%d_%H%M%S}.txt", e.surova_odpoved)
        return _preruseni(beh, zdroje, pisatel, hodnotitel, hlaseni, e.hlaska)
    except KeyboardInterrupt:
        _log.exception(HLASKA_CTRL_C)
        return _preruseni(beh, zdroje, pisatel, hodnotitel, hlaseni, HLASKA_CTRL_C)
    except Exception:
        _log.exception("Neočekávaná chyba programu.")
        return _preruseni(beh, zdroje, pisatel, hodnotitel, hlaseni, HLASKA_NEOCEKAVANA)


def dokonci(
    beh: Beh,
    zdroje: Zdroje,
    pisatel: Model,
    hodnotitel: Model,
    hlaseni: Callable[[str], None],
    sablona: Path | None,
) -> int:
    """Doběhne smyčku a vytvoří výstupy. Vrací 0 = hotovo, 1 = běh přerušen (uložen, lze pokračovat).

    Po dobu běhu je na logger `refiner` připojen soubor data/beh.log (technické detaily, traceback).
    """
    with _log_behu(beh):
        _log.info("Běh %s: start (stav %s, hotové kroky: %s).",
                  beh.slozka.name, beh.stav.stav, ", ".join(beh.stav.kroky) or "žádné")
        return _dokonci(beh, zdroje, pisatel, hodnotitel, hlaseni, sablona)


@contextmanager
def _log_behu(beh: Beh) -> Iterator[None]:
    """Připojí na logger `refiner` soubor data/beh.log (připisuje se na konec)."""
    logger = logging.getLogger("refiner")
    handler = logging.FileHandler(beh.slozka / _LOG, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    puvodni_uroven = logger.level
    logger.addHandler(handler)
    if logger.getEffectiveLevel() > logging.INFO:
        logger.setLevel(logging.INFO)
    try:
        yield
    finally:
        logger.removeHandler(handler)
        logger.setLevel(puvodni_uroven)
        handler.close()


# ---------------------------------------------------------------- porovnání s referencí

def porovnej_beh(
    beh: Beh,
    zdroje: Zdroje,
    reference_md: str,
    hodnotitel: Model,
    hlaseni: Callable[[str], None],
    nazev_reference: str | None = None,
) -> int:
    """Porovná dokončený běh s referencí. Vrací 0 = hotovo, 1 = porovnání selhalo (lze zopakovat),
    2 = chyba konfigurace (prompt). Stav běhu zůstává `dokoncen`."""
    with _log_behu(beh):
        _log.info("Porovnání s referencí %s: start.", nazev_reference or "(bez názvu)")
        try:
            html = porovnej(beh, zdroje, reference_md, hodnotitel, hlaseni, nazev_reference=nazev_reference)
        except ChybaKonfigurace as e:
            hlaseni(str(e))
            return 2
        except ChybaModelu as e:
            _log.exception("Chyba modelu při porovnání: %s", e.hlaska)
            if e.surova_odpoved is not None:
                beh.zapis_pevny(f"data/surova_odpoved_porovnani_{datetime.now():%Y%m%d_%H%M%S}.txt",
                                e.surova_odpoved)
            # Hlášky chyb radí pokracovat.bat; dokončený běh se ale porovnává znovu přes porovnat.bat.
            hlaseni(e.hlaska.replace("pokracovat.bat", "porovnat.bat"))
            hlaseni(HLASKA_POROVNAT_ZNOVU)
            return 1
        except KeyboardInterrupt:
            _log.exception(HLASKA_CTRL_C)
            hlaseni(HLASKA_CTRL_C)
            hlaseni(HLASKA_POROVNAT_ZNOVU)
            return 1
        except Exception:
            _log.exception("Neočekávaná chyba při porovnání.")
            hlaseni(HLASKA_NEOCEKAVANA)
            return 1
        _log.info("Porovnání dokončeno: %s", html)
        hlaseni(f"Hotovo. Porovnání s referencí: {html}")
        return 0

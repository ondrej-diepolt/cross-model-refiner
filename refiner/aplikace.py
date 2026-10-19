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

from refiner.artifacts import (
    CONFIGURATION_DIRECTORY, LOG_FILE, MATERIALS_FILE, STATE_FILE, PROMPT_SNAPSHOT_NAMES,
    canonical_profile_id,
)
from refiner.run import Run
from refiner.configuration import (
    ConfigurationError,
    Configuration,
    criteria_path_for_request,
    load_configuration,
    load_settings,
)
from refiner.steps import Sources
from refiner.models.errors import ModelError
from refiner.models.interface import Model
from refiner.porovnani import porovnej
from refiner.loop import run_loop
from refiner.input import InputError, read_as_markdown, read_materials, resolve_materials_directory
from refiner.vystup.docx import exportuj_docx
from refiner.vystup.prehled import vytvor_prehled

_log = logging.getLogger(__name__)

HLASKA_CTRL_C = "Přerušeno uživatelem (Ctrl+C)."
HLASKA_NEOCEKAVANA = "Neočekávaná chyba programu – podrobnosti v data/beh.log."
HLASKA_POKRACOVAT = "Pokračovat: pokracovat.bat"
HLASKA_POROVNAT_ZNOVU = "Stav běhu se nezměnil; porovnání zopakujete spuštěním porovnat.bat."


# ---------------------------------------------------------------- zahájení a obnovení

def _modely_z_repozitare(
    beh: Run,
    konfigurace: Configuration,
    koren: Path,
    hlaseni: Callable[[str], None] | None,
) -> Configuration:
    """Nahradí oddíly `modely` a `ceny_usd_za_milion` hodnotami z aktuálního koren/settings.yaml.

    Opravené nastavení modelů (limity tokenů, časový limit, název modelu) se tak projeví
    i v pokračujícím běhu. Smyčka, váhy, profil a prompty zůstávají z kopie běhu, aby skóre
    zůstalo reprodukovatelné. Vadný nebo chybějící soubor v repozitáři → kopie běhu s varováním.
    """
    soubor = koren / "settings.yaml"
    with _log_behu(beh):
        try:
            aktualni = load_settings(soubor)
        except ConfigurationError as e:
            zprava = (f"Varování: nastavení modelů z {soubor} nelze použít ({e}); běh pokračuje "
                      f"s nastavením modelů z kopie ve složce běhu ({CONFIGURATION_DIRECTORY}/nastaveni.yaml).")
            _log.warning(zprava)
            if hlaseni is not None:
                hlaseni(zprava)
            return konfigurace
        _log.info("Nastavení: oddíly models a prices_usd_per_million z aktuálního %s; smyčka, váhy, "
                  "profil a prompty z kopie běhu (%s).", soubor, CONFIGURATION_DIRECTORY)
    nastaveni = konfigurace.settings.model_copy(update={
        "models": aktualni.models, "prices_usd_per_million": aktualni.prices_usd_per_million})
    return replace(konfigurace, settings=nastaveni)


def _nacti_zdroje(beh: Run, koren: Path | None = None,
                  hlaseni: Callable[[str], None] | None = None) -> Sources:
    """Zdroje z kopií ve složce běhu (konfigurace, prompty, poptávka, podklady).

    Je-li zadán `koren`, oddíly `modely` a `ceny_usd_za_milion` se vezmou z aktuálního
    koren/settings.yaml (viz _modely_z_repozitare).
    """
    konf_slozka = beh.directory / CONFIGURATION_DIRECTORY
    kriteria = konf_slozka / "kriteria.yaml"
    konfigurace = load_configuration(
        konf_slozka / "nastaveni.yaml",
        konf_slozka / "profil.yaml",
        kriteria if kriteria.exists() else None,
    )
    # Kopie profilu se jmenuje profil.yaml; název profilu (pro FINALNI_<profil>) je ve stavu běhu.
    konfigurace = replace(konfigurace, profile_id=beh.state.profile_id,
                         output_profile_name=beh.state.output_profile_name)
    if koren is not None:
        konfigurace = _modely_z_repozitare(beh, konfigurace, koren, hlaseni)
    podklady = beh.directory / MATERIALS_FILE
    return Sources(
        request=beh.text('request'),
        materials=podklady.read_text(encoding="utf-8") if podklady.exists() else "",
        configuration=konfigurace,
        prompts=konf_slozka / "prompty",
    )


def zahaj_beh(koren: Path, vstup: Path, profil: str, ted: datetime,
              nanecisto: bool = False) -> tuple[Run, Sources]:
    """Založí běh v koren/output: kopie konfigurace a promptů, krok poptavka a data/podklady.md.

    `nanecisto` se uloží do stavu běhu (ukázkový běh s falešnými modely).
    """
    nastaveni = koren / "settings.yaml"
    profil = canonical_profile_id(profil)
    soubor_profilu = koren / "profiles" / f"{profil}.yaml"
    kriteria = criteria_path_for_request(vstup)
    # Chyby konfigurace a vstupu se ohlásí dřív, než vznikne složka běhu.
    load_configuration(nastaveni, soubor_profilu, kriteria)
    poptavka = read_as_markdown(vstup)
    podklady = read_materials(resolve_materials_directory(koren))

    beh = Run.new(koren / "output", vstup.name, profil, ted, dry_run=nanecisto)
    konf_slozka = beh.directory / CONFIGURATION_DIRECTORY
    konf_slozka.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(nastaveni, konf_slozka / "nastaveni.yaml")
    shutil.copyfile(soubor_profilu, konf_slozka / "profil.yaml")
    (konf_slozka / "prompty").mkdir()
    for name, snapshot_name in PROMPT_SNAPSHOT_NAMES.items():
        source = koren / 'prompts' / f"{name}.md"
        if not source.is_file():
            source = koren / 'prompts' / snapshot_name
        shutil.copyfile(source, konf_slozka / "prompty" / snapshot_name)
    if kriteria is not None:
        shutil.copyfile(kriteria, konf_slozka / "kriteria.yaml")
    beh.write_fixed(MATERIALS_FILE, podklady)
    beh.write('request', "poptavka.md", poptavka)
    return beh, _nacti_zdroje(beh)


def _otevri(slozka: Path) -> Run:
    if not (slozka / STATE_FILE).is_file():
        raise InputError(f"Složka {slozka} není složka běhu (chybí {STATE_FILE}).")
    try:
        return Run.open(slozka)
    except (OSError, ValidationError) as e:
        raise InputError(f"Stav běhu ve složce {slozka} nelze přečíst ({STATE_FILE}).") from e


def obnov_beh(
    slozka: Path,
    koren: Path | None = None,
    nanecisto: bool | None = None,
    hlaseni: Callable[[str], None] | None = None,
) -> tuple[Run, Sources]:
    """Otevře přerušený běh; konfiguraci, prompty i vstupy bere z kopií ve složce běhu.

    Se zadaným `koren` bere oddíly `modely` a `ceny_usd_za_milion` z aktuálního
    koren/settings.yaml. Se zadaným `nanecisto` odmítne běh jiného režimu (ukázkový/ostrý).
    """
    beh = _otevri(slozka)
    if beh.state.status == 'completed':
        raise InputError(f"Běh {slozka.name} je už dokončený.")
    if not beh.is_done('request'):
        raise InputError(f"Běh {slozka.name} nelze obnovit: chybí uložená poptávka.")
    if nanecisto is not None and beh.state.dry_run != nanecisto:
        if beh.state.dry_run:
            raise InputError(f"Běh {slozka.name} je ukázkový (--nanecisto, falešné modely); "
                              "pokračovat v něm lze jen s volbou --nanecisto.")
        raise InputError(f"Běh {slozka.name} je ostrý běh se skutečnými modely; s volbou --nanecisto "
                          "v něm pokračovat nelze. Spusťte pokracovat.bat bez --nanecisto.")
    return beh, _nacti_zdroje(beh, koren, hlaseni)


def otevri_dokonceny(
    slozka: Path,
    koren: Path | None = None,
    nanecisto: bool | None = None,
    hlaseni: Callable[[str], None] | None = None,
) -> tuple[Run, Sources]:
    """Otevře dokončený běh k porovnání; zdroje bere z kopií ve složce běhu.

    `koren` a `nanecisto` jako u obnov_beh (porovnání volá skutečný GPT, ukázkový běh odmítne).
    """
    beh = _otevri(slozka)
    if beh.state.status != 'completed':
        raise InputError(f"Běh {slozka.name} není dokončený; porovnat lze jen dokončený běh.")
    if nanecisto is not None and beh.state.dry_run != nanecisto:
        if beh.state.dry_run:
            raise InputError(f"Běh {slozka.name} je ukázkový (--nanecisto) s falešnými texty; "
                              "s referencí ho porovnat nelze.")
        raise InputError(f"Běh {slozka.name} je ostrý běh; v ukázkovém režimu ho porovnat nelze.")
    return beh, _nacti_zdroje(beh, koren, hlaseni)


def obnov_prompty_porovnani(beh: Run, prompty: Path) -> None:
    """Zkopíruje aktuální prompty porovnání z `prompty` do kopie konfigurace běhu.

    Porovnání je nástroj ladění: má používat aktuální prompty porovnání (i u běhů založených
    dřív, než prompty existovaly), a kopie ve složce běhu pak ukazuje, s čím se porovnávalo.
    Ostatní prompty (hodnoceni.md pro kalibraci) zůstávají z běhu.
    """
    cil = beh.directory / CONFIGURATION_DIRECTORY / "prompty"
    for name, snapshot_name in PROMPT_SNAPSHOT_NAMES.items():
        if not name.startswith("comparison_"):
            continue
        source = prompty / f"{name}.md"
        if not source.is_file():
            source = prompty / snapshot_name
        if source.is_file():
            cil.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, cil / snapshot_name)


def najdi_posledni_beh(output: Path, stavy: set[str], nanecisto: bool | None = None) -> Path | None:
    """Nejnovější (podle `vytvoreno`) složka běhu v `output` s jedním z daných stavů.

    Se zadaným `nanecisto` přeskočí běhy jiného režimu (ukázkové/ostré).
    """
    if not output.is_dir():
        return None
    nalezene: list[tuple[datetime, str, Path]] = []
    for slozka in output.iterdir():
        if not (slozka / STATE_FILE).is_file():
            continue
        try:
            stav = Run.open(slozka).state
        except (OSError, ValidationError):
            continue
        if stav.status in stavy and (nanecisto is None or stav.dry_run == nanecisto):
            nalezene.append((stav.created_at, slozka.name, slozka))
    return max(nalezene)[2] if nalezene else None


# ---------------------------------------------------------------- dokončení

def _preruseni(
    beh: Run,
    sources: Sources,
    pisatel: Model,
    hodnotitel: Model,
    hlaseni: Callable[[str], None],
    chyba: str,
) -> int:
    """Uloží běh jako přerušený, zkusí vytvořit přehled a ohlásí, jak pokračovat. Vrací 1."""
    try:
        # Spotřeba volání, která vrátila odpověď, ale krok pak neprošel kontrolou.
        zbytek = pisatel.take_usage() + hodnotitel.take_usage()
        if zbytek:
            beh.add_usage(zbytek)
    except Exception:
        _log.exception("Spotřebu přerušeného kroku se nepodařilo uložit.")
    beh.finish('interrupted', error=chyba)
    try:
        vytvor_prehled(beh, sources.configuration)
    except Exception:
        _log.exception("Přehled přerušeného běhu se nepodařilo vytvořit.")
    hlaseni(chyba)
    hlaseni(f"Rozpracovaný běh je uložen ve složce: {beh.directory}")
    hlaseni(HLASKA_POKRACOVAT)
    return 1


def _dokonci(
    beh: Run,
    sources: Sources,
    pisatel: Model,
    hodnotitel: Model,
    hlaseni: Callable[[str], None],
    sablona: Path | None,
) -> int:
    try:
        vysledek = run_loop(beh, sources, pisatel, hodnotitel, hlaseni)
        finalni = beh.text(f"draft_{vysledek.final_version}")
        nazev = sources.configuration.output_profile_name
        beh.write_fixed(f"FINALNI_{nazev}.md", finalni)
        try:
            exportuj_docx(finalni, beh.directory / f"FINALNI_{nazev}.docx", sablona)
        except Exception as e:
            _log.exception("Export do DOCX selhal.")
            beh.add_warning(
                f"Export do DOCX se nepodařil ({e}); finální text je v souboru FINALNI_{nazev}.md."
            )
        beh.finish('completed', vysledek.reason, final_version=vysledek.final_version)
        prehled = vytvor_prehled(beh, sources.configuration)
        _log.info("Běh dokončen (%s, finální verze %d).", vysledek.reason, vysledek.final_version)
        hlaseni(f"Hotovo. Přehled běhu: {prehled}")
        return 0
    except ModelError as e:
        _log.exception("Chyba modelu: %s", e.message)
        if e.raw_response is not None:
            beh.write_fixed(f"data/surova_odpoved_{datetime.now():%Y%m%d_%H%M%S}.txt", e.raw_response)
        return _preruseni(beh, sources, pisatel, hodnotitel, hlaseni, e.message)
    except KeyboardInterrupt:
        _log.exception(HLASKA_CTRL_C)
        return _preruseni(beh, sources, pisatel, hodnotitel, hlaseni, HLASKA_CTRL_C)
    except Exception:
        _log.exception("Neočekávaná chyba programu.")
        return _preruseni(beh, sources, pisatel, hodnotitel, hlaseni, HLASKA_NEOCEKAVANA)


def dokonci(
    beh: Run,
    sources: Sources,
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
                  beh.directory.name, beh.state.status, ", ".join(beh.state.steps) or "žádné")
        return _dokonci(beh, sources, pisatel, hodnotitel, hlaseni, sablona)


@contextmanager
def _log_behu(beh: Run) -> Iterator[None]:
    """Připojí na logger `refiner` soubor data/beh.log (připisuje se na konec)."""
    logger = logging.getLogger("refiner")
    handler = logging.FileHandler(beh.directory / LOG_FILE, encoding="utf-8")
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
    beh: Run,
    sources: Sources,
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
            html = porovnej(beh, sources, reference_md, hodnotitel, hlaseni, nazev_reference=nazev_reference)
        except ConfigurationError as e:
            hlaseni(str(e))
            return 2
        except ModelError as e:
            _log.exception("Chyba modelu při porovnání: %s", e.message)
            if e.raw_response is not None:
                beh.write_fixed(f"data/surova_odpoved_porovnani_{datetime.now():%Y%m%d_%H%M%S}.txt",
                                e.raw_response)
            # Hlášky chyb radí pokracovat.bat; dokončený běh se ale porovnává znovu přes porovnat.bat.
            hlaseni(e.message.replace("pokracovat.bat", "porovnat.bat"))
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

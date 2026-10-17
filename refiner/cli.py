"""Příkazová řádka (design kap. 8): nový běh, --pokracovat, --nanecisto, porovnat; výběr vstupu a profilu.

Návratové kódy: 0 hotovo, 1 běh (nebo porovnání) přerušen, uložen a lze ho zopakovat,
2 chyba konfigurace, vstupu nebo uživatele. Do konzole jdou jen české hlášky; technické detaily zapisuje
aplikace.dokonci do data/beh.log (žádný konzolový handler logování se tu nepřidává).
"""
from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TextIO

from dotenv import load_dotenv

from refiner.aplikace import (
    HLASKA_CTRL_C,
    dokonci,
    najdi_posledni_beh,
    obnov_beh,
    obnov_prompty_porovnani,
    otevri_dokonceny,
    porovnej_beh,
    zahaj_beh,
)
from refiner.konfigurace import (
    ChybaKonfigurace,
    Konfigurace,
    cesta_kriterii_k_poptavce,
    dostupne_profily,
    nacti_konfiguraci,
)
from refiner.modely.chyby import ChybaModelu, Sluzba
from refiner.modely.claude import ClaudeModel
from refiner.modely.falesne import demo_modely
from refiner.modely.gpt import GptModel
from refiner.modely.rozhrani import Model
from refiner.porovnani import nacti_referenci, najdi_referenci
from refiner.vstup import ChybaVstupu, najdi_vstupy

KOREN = Path(__file__).resolve().parent.parent

KLICE: tuple[tuple[str, Sluzba], ...] = (("ANTHROPIC_API_KEY", "Anthropic"), ("OPENAI_API_KEY", "OpenAI"))
KLIC_HODNOTITELE: tuple[tuple[str, Sluzba], ...] = (("OPENAI_API_KEY", "OpenAI"),)

HLASKA_VZOR_ENV = "Vzor najdete v souboru .env.example."
HLASKA_ENV_KODOVANI = "Soubor .env nelze přečíst – uložte ho v kódování UTF-8."
HLASKA_ZADNY_VSTUP = "Ve složce input/ není žádná poptávka (DOCX, MD nebo TXT)."
HLASKA_ZADNY_PROFIL = "Ve složce profily/ není žádný profil dokumentu (*.yaml)."
HLASKA_ZADNY_PRERUSENY = "Ve složce output/ není žádný přerušený běh, ve kterém by šlo pokračovat."
HLASKA_ZADNY_DOKONCENY = "Ve složce output/ není žádný dokončený běh, který by šlo porovnat s referencí."
HLASKA_POROVNAT_VOLBY = ("Příkaz porovnat nejde kombinovat s --nanecisto ani --pokracovat "
                         "(porovnání volá skutečný model GPT).")
HLASKA_KONEC_VSTUPU = "Volba nebyla zadána (konec vstupu)."
HLASKA_NANECISTO = "Ukázkový režim --nanecisto: falešné modely, bez volání API a bez nákladů."

PRERUSENE_STAVY = {"prerusen", "bezi"}

TovarnaModelu = Callable[[Konfigurace, bool], tuple[Model, Model]]


# ---------------------------------------------------------------- konzole

def _priprav_proud(proud: TextIO) -> None:
    """Přepne proud na UTF-8 s náhradou nezobrazitelných znaků, pokud to proud umí."""
    reconfigure = getattr(proud, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        pass


class _Konzole:
    """Jediné místo, kudy jdou hlášky do konzole; po každém zápisu flush().

    Hláška končící „…“ zůstane rozepsaná na řádku a následné „hotovo…“ se připíše za ni
    (`[3/12] Hodnocení 1… hotovo, skóre 7,9`).
    """

    def __init__(self, proud: TextIO | None):
        self._proud = proud
        self._rozepsano = False

    def _zapis(self, text: str) -> None:
        if self._proud is None:
            return
        try:
            self._proud.write(text)
        except UnicodeEncodeError:
            kodovani = getattr(self._proud, "encoding", None) or "ascii"
            self._proud.write(text.encode(kodovani, errors="replace").decode(kodovani))
        self._proud.flush()

    def __call__(self, text: str) -> None:
        if self._rozepsano:
            self._rozepsano = False
            if text.startswith("hotovo"):
                self._zapis(f" {text}\n")
                return
            self._zapis("\n")
        if text.endswith("…"):
            self._zapis(text)
            self._rozepsano = True
        else:
            self._zapis(f"{text}\n")

    def ukonci(self) -> None:
        if self._rozepsano:
            self._rozepsano = False
            self._zapis("\n")


def _vyber(konzole: _Konzole, vstup_fn: Callable[[str], str], otazka: str, moznosti: list[str]) -> int:
    """Očíslovaný výběr; neplatná volba se zopakuje. Vrací index zvolené možnosti."""
    konzole(otazka)
    for i, moznost in enumerate(moznosti, start=1):
        konzole(f"  {i}) {moznost}")
    n = len(moznosti)
    while True:
        odpoved = vstup_fn(f"Zadejte číslo 1–{n}: ").strip()
        if odpoved.isdigit() and 1 <= int(odpoved) <= n:
            return int(odpoved) - 1
        konzole(f"Neplatná volba „{odpoved}“. Zadejte číslo 1–{n}.")


# ---------------------------------------------------------------- příprava běhu

def _vychozi_tovarna(konfigurace: Konfigurace, nanecisto: bool) -> tuple[Model, Model]:
    if nanecisto:
        return demo_modely()
    modely = konfigurace.nastaveni.modely
    return ClaudeModel(modely), GptModel(modely)


def _vychozi_hodnotitel(konfigurace: Konfigurace) -> Model:
    return GptModel(konfigurace.nastaveni.modely)


def _chybejici_klice(klice: tuple[tuple[str, Sluzba], ...] = KLICE) -> list[Sluzba]:
    return [sluzba for promenna, sluzba in klice if not os.environ.get(promenna, "").strip()]


def _otazka_profilu(nazvy: list[str]) -> str:
    """„Nabídka, nebo směrnice?“ z názvů profilů."""
    male = [n[:1].lower() + n[1:] for n in nazvy[1:]]
    casti = [nazvy[0], *male]
    return ", ".join(casti[:-1]) + ", nebo " + casti[-1] + "?"


def _zvol_profil(koren: Path, konzole: _Konzole, vstup_fn: Callable[[str], str]) -> str:
    profily = dostupne_profily(koren / "profily")
    if not profily:
        raise ChybaKonfigurace(HLASKA_ZADNY_PROFIL)
    if len(profily) == 1:
        return profily[0]
    nastaveni = koren / "nastaveni.yaml"
    nazvy = [nacti_konfiguraci(nastaveni, koren / "profily" / f"{p}.yaml").profil.nazev for p in profily]
    return profily[_vyber(konzole, vstup_fn, _otazka_profilu(nazvy), nazvy)]


def _zvol_vstup(koren: Path, konzole: _Konzole, vstup_fn: Callable[[str], str]) -> Path:
    slozka = koren / "input"
    vstupy = najdi_vstupy(slozka) if slozka.is_dir() else []
    if not vstupy:
        raise ChybaVstupu(HLASKA_ZADNY_VSTUP)
    if len(vstupy) == 1:
        return vstupy[0]
    return vstupy[_vyber(konzole, vstup_fn, "Kterou poptávku zpracovat?", [p.name for p in vstupy])]


def _slozka_behu(koren: Path, hodnota: str, stavy: set[str]) -> Path | None:
    if not hodnota:
        return najdi_posledni_beh(koren / "output", stavy)
    cesta = Path(hodnota)
    if not cesta.is_absolute() and not cesta.exists() and (koren / "output" / cesta).exists():
        cesta = koren / "output" / cesta
    return cesta


def _cesta_reference(koren: Path, hodnota: str | None) -> Path:
    if hodnota is None:
        return najdi_referenci(koren)
    cesta = Path(hodnota)
    if not cesta.is_absolute() and not cesta.exists() and (koren / cesta).exists():
        cesta = koren / cesta
    return cesta


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m refiner",
        description="Cross-model refiner: Claude píše dokument, GPT ho hodnotí, Claude ho vylepšuje.",
    )
    p.add_argument("--nanecisto", action="store_true",
                   help="ukázkový běh s falešnými modely, bez volání API a bez nákladů")
    p.add_argument("--pokracovat", nargs="?", const="", default=None, metavar="SLOZKA",
                   help="dokončí přerušený běh (bez hodnoty poslední přerušený v output/)")
    podprikazy = p.add_subparsers(dest="prikaz", metavar="PRIKAZ")
    porovnat = podprikazy.add_parser(
        "porovnat", help="porovná dokončený běh s referenční nabídkou (potřebuje jen OPENAI_API_KEY)",
        description="Porovná dokončený běh s ručně dotaženou referenční nabídkou (výstup porovnani.html).",
    )
    porovnat.add_argument("slozka", nargs="?", default="", metavar="SLOZKA",
                          help="složka běhu (bez hodnoty poslední dokončený běh v output/)")
    porovnat.add_argument("--reference", default=None, metavar="SOUBOR",
                          help="referenční nabídka (výchozí: jediný soubor ve složce examples/)")
    return p


# ---------------------------------------------------------------- hlavní funkce

def main(
    argv: list[str] | None = None,
    *,
    koren: Path | None = None,
    vstup_fn: Callable[[str], str] = input,
    vystup: TextIO | None = None,
    tovarna_modelu: TovarnaModelu | None = None,
    otevrit_prehled: bool = False,
) -> int:
    """Spustí nový běh nebo pokračuje v přerušeném. Vrací 0 / 1 / 2 (viz docstring modulu)."""
    proud = vystup if vystup is not None else sys.stdout
    if proud is not None:
        _priprav_proud(proud)
    konzole = _Konzole(proud)
    try:
        args = _parser().parse_args(argv)
    except SystemExit as e:   # --help nebo neplatný argument (argparse vypíše na stderr)
        return e.code if isinstance(e.code, int) else 2
    # Porovnání volá jen hodnotitele: skutečný GPT nepotřebuje klíč Anthropic.
    hodnotitel_fn = ((lambda konf: tovarna_modelu(konf, False)[1]) if tovarna_modelu is not None
                     else _vychozi_hodnotitel)
    try:
        return _spust(args, Path(koren) if koren is not None else KOREN, vstup_fn, konzole,
                      tovarna_modelu or _vychozi_tovarna, hodnotitel_fn, otevrit_prehled)
    finally:
        konzole.ukonci()


def _spust(
    args: argparse.Namespace,
    koren: Path,
    vstup_fn: Callable[[str], str],
    konzole: _Konzole,
    tovarna: TovarnaModelu,
    hodnotitel_fn: Callable[[Konfigurace], Model],
    otevrit_prehled: bool,
) -> int:
    porovnat = args.prikaz == "porovnat"
    if porovnat and (args.nanecisto or args.pokracovat is not None):
        konzole(HLASKA_POROVNAT_VOLBY)
        return 2
    try:
        load_dotenv(koren / ".env", encoding="utf-8")
    except (UnicodeDecodeError, OSError):   # .env uložený v ANSI/cp1250 nebo UTF-16
        konzole(HLASKA_ENV_KODOVANI)
        return 2
    if args.nanecisto:
        konzole(HLASKA_NANECISTO)
    else:
        chybi = _chybejici_klice(KLIC_HODNOTITELE if porovnat else KLICE)
        for sluzba in chybi:
            konzole(f"{ChybaModelu('klic', sluzba).hlaska} {HLASKA_VZOR_ENV}")
        if chybi:
            return 2

    try:
        if porovnat:
            slozka = _slozka_behu(koren, args.slozka, {"dokoncen"})
            if slozka is None:
                konzole(HLASKA_ZADNY_DOKONCENY)
                return 2
            beh, zdroje = otevri_dokonceny(slozka)
            obnov_prompty_porovnani(beh, koren / "prompty")
            reference = _cesta_reference(koren, args.reference)
            reference_md = nacti_referenci(reference)
            hodnotitel = hodnotitel_fn(zdroje.konfigurace)
            konzole(f"Porovnávám běh {beh.slozka} s referencí {reference.name}")
        elif args.pokracovat is not None:
            slozka = _slozka_behu(koren, args.pokracovat, PRERUSENE_STAVY)
            if slozka is None:
                konzole(HLASKA_ZADNY_PRERUSENY)
                return 2
            beh, zdroje = obnov_beh(slozka)
            konzole(f"Pokračuji v běhu: {beh.slozka}")
            pisatel, hodnotitel = tovarna(zdroje.konfigurace, args.nanecisto)
        else:
            vstup = _zvol_vstup(koren, konzole, vstup_fn)
            profil = _zvol_profil(koren, konzole, vstup_fn)
            konfigurace = nacti_konfiguraci(
                koren / "nastaveni.yaml",
                koren / "profily" / f"{profil}.yaml",
                cesta_kriterii_k_poptavce(vstup),
            )
            pisatel, hodnotitel = tovarna(konfigurace, args.nanecisto)
            konzole(f"Poptávka: {vstup.name}, profil: {konfigurace.profil.nazev}")
            beh, zdroje = zahaj_beh(koren, vstup, profil, datetime.now())
            konzole(f"Složka běhu: {beh.slozka}")
    except (ChybaKonfigurace, ChybaVstupu) as e:
        konzole(str(e))
        return 2
    except ChybaModelu as e:
        konzole(e.hlaska)
        return 2
    except EOFError:
        konzole(HLASKA_KONEC_VSTUPU)
        return 2
    except KeyboardInterrupt:
        konzole(HLASKA_CTRL_C)
        return 2
    except Exception as e:   # např. poškozený DOCX (pandoc) nebo soubor otevřený jiným programem
        konzole(f"Běh se nepodařilo připravit: {type(e).__name__}: {e}")
        return 2

    if porovnat:
        kod = porovnej_beh(beh, zdroje, reference_md, hodnotitel, konzole, reference.name)
        html = "porovnani.html"
    else:
        sablona = koren / "podklady" / "sablona.docx"
        kod = dokonci(beh, zdroje, pisatel, hodnotitel, konzole,
                      sablona if sablona.is_file() else None)
        html = "prehled.html"
    if kod == 0 and otevrit_prehled:
        try:
            webbrowser.open((beh.slozka / html).resolve().as_uri())
        except Exception:
            pass   # přehled je jen pohodlí navíc; cestu už vypsal dokonci() / porovnej_beh()
    return kod

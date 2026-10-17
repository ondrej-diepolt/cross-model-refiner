"""Pomocné funkce pro testy: hotové objekty nastavení, kritérií a hodnocení."""
from __future__ import annotations

from pathlib import Path

from refiner.data import (
    Hodnoceni,
    Nalezitost,
    Navrh,
    Posouzeni,
    Rozhodnuti,
    SkoreKriteria,
    VymyslenyFakt,
    Kriterium,
    sestav_kriteria,
)
from refiner.konfigurace import Nastaveni, nacti_konfiguraci
from refiner.kroky import Zdroje

KOREN = Path(__file__).parent.parent

POPTAVKA_TEST = """# Poptávka – tabletop cvičení

Zadavatel poptává přípravu a vedení tabletop cvičení pro krizový štáb (do 20 osob).

Nabídka proto musí obsahovat:
- popis metodiky cvičení,
- harmonogram a hlavní milníky realizace,
- cenu za celé plnění.
"""


def zdroje_test(koren_repa: Path) -> Zdroje:
    """Zdroje s krátkou poptávkou, bez podkladů, s konfigurací a prompty z repa."""
    konf = nacti_konfiguraci(koren_repa / "nastaveni.yaml", koren_repa / "profily" / "nabidka.yaml")
    return Zdroje(poptavka=POPTAVKA_TEST, podklady="", konfigurace=konf, prompty=koren_repa / "prompty")


def nastaveni_test() -> Nastaveni:
    return nacti_konfiguraci(KOREN / "nastaveni.yaml", KOREN / "profily" / "nabidka.yaml").nastaveni


def kriteria_test(n_nalezitosti: int = 3) -> list[Kriterium]:
    konf = nacti_konfiguraci(KOREN / "nastaveni.yaml", KOREN / "profily" / "nabidka.yaml")
    nal = [Nalezitost(id=f"N{i}", text=f"Náležitost {i}", citace=f"Citace {i}")
           for i in range(1, n_nalezitosti + 1)]
    return sestav_kriteria(nal, konf.kriteria_profilu)


def hodnoceni(
    zaklad: float = 8.0,
    prepsat: dict[str, float] | None = None,
    fakta: int = 0,
    navrhy: int = 2,
    kriteria: list[Kriterium] | None = None,
) -> Hodnoceni:
    kriteria = kriteria if kriteria is not None else kriteria_test()
    prepsat = prepsat or {}
    return Hodnoceni(
        kriteria=[
            SkoreKriteria(id=k.id, skore=prepsat.get(k.id, zaklad), zduvodneni="Zdůvodnění.", dukaz="Důkaz.")
            for k in kriteria
        ],
        vymyslena_fakta=[VymyslenyFakt(citace=f"Fakt {i}", proc="Není ve vstupu.") for i in range(fakta)],
        tvrzeni_k_overeni=[],
        navrhy=[
            Navrh(id=f"V{i}", kriterium="B1", misto=f"Místo {i}", problem="Problém.",
                  navrh="Návrh.", priorita="stredni")
            for i in range(1, navrhy + 1)
        ],
        celkovy_komentar="Komentář.",
    )


def posouzeni(h: Hodnoceni, rozhodnuti: str = "prijato") -> Posouzeni:
    return Posouzeni(
        rozhodnuti=[
            Rozhodnuti(id_navrhu=n.id, opora="Opora.", predpoklad="Předpoklad.", dusledek="Důsledek.",
                       rozhodnuti=rozhodnuti, zduvodneni="Zdůvodnění.", jak_zapracovat="Takto.")
            for n in h.navrhy
        ],
        shrnuti="Shrnutí.",
    )

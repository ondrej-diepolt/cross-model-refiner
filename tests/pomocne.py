"""Pomocné funkce pro testy: hotové objekty nastavení, kritérií a hodnocení."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from refiner.beh import Beh
from refiner.data import (
    Hodnoceni,
    Nalezitost,
    Navrh,
    Posouzeni,
    Rozhodnuti,
    SkoreKriteria,
    VymyslenyFakt,
    VystupNalezitosti,
    Kriterium,
    sestav_kriteria,
)
from refiner.konfigurace import Nastaveni, nacti_konfiguraci
from refiner.kroky import Zdroje
from refiner.models.fakes import FakeModel

KOREN = Path(__file__).parent.parent

POPTAVKA_TEST = """# Poptávka – tabletop cvičení

Zadavatel poptává přípravu a vedení tabletop cvičení pro krizový štáb (do 20 osob).

Nabídka proto musí obsahovat:
- popis metodiky cvičení,
- harmonogram a hlavní milníky realizace,
- cenu za celé plnění.
"""


NALEZITOSTI_TEST = [
    Nalezitost(id="N1", text="Metodika", citace="popis metodiky cvičení"),
    Nalezitost(id="N2", text="Harmonogram", citace="harmonogram a hlavní milníky realizace"),
    Nalezitost(id="N3", text="Cena", citace="cenu za celé plnění"),
]


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


def beh_test(tmp_path: Path, zdroje: Zdroje) -> Beh:
    """Nový běh s už zapsaným krokem poptavka (01_poptavka.md), jako v reálném toku."""
    beh = Beh.novy(tmp_path, "poptavka.md", zdroje.konfigurace.profil_nazev, datetime(2026, 10, 17, 9, 0))
    beh.zapis("poptavka", "poptavka.md", zdroje.poptavka)
    return beh


def text_navrhu(verze: int) -> str:
    """Krátký dokument, který projde kontrolou přepisu (stejný nadpis, podobná délka)."""
    return f"# Nabídka\n\nVerze {verze}: popis metodiky cvičení, harmonogram a cena za celé plnění."


def odpovedi_skriptu(
    skore_po_hodnocenich: list[float], rozhodnuti: str = "prijato"
) -> tuple[dict[str, list], dict[str, list]]:
    """Odpovědi pisatele a hodnotitele pro všechny kroky smyčky (klíč = přesné ID kroku).

    Skóre musí projít kontrolou hodnocení (1–10 po 0,5); např. 9.5 dá celkem 9,6 = cíl splněn.
    """
    for s in skore_po_hodnocenich:
        if not (1 <= s <= 10 and s * 2 == int(s * 2)):
            raise ValueError(f"skript: skóre {s} není 1–10 v kroku 0,5 – kontrola hodnocení by ho odmítla")
    pisatel: dict[str, list] = {
        "nalezitosti": [VystupNalezitosti(nalezitosti=NALEZITOSTI_TEST)],
        "navrh_1": [text_navrhu(1)],
    }
    hodnotitel: dict[str, list] = {}
    for k, skore in enumerate(skore_po_hodnocenich, start=1):
        h = hodnoceni(skore)
        hodnotitel[f"hodnoceni_{k}"] = [h]
        pisatel[f"posouzeni_{k}"] = [posouzeni(h, rozhodnuti)]
        pisatel[f"navrh_{k + 1}"] = [text_navrhu(k + 1)]
    return pisatel, hodnotitel


def skript(
    skore_po_hodnocenich: list[float], rozhodnuti: str = "prijato"
) -> tuple[FakeModel, FakeModel]:
    """Falešný pisatel a hodnotitel; hodnocení k má všem kritériím skore_po_hodnocenich[k-1]."""
    pisatel, hodnotitel = odpovedi_skriptu(skore_po_hodnocenich, rozhodnuti)
    return FakeModel(pisatel, name="claude-falesny"), FakeModel(hodnotitel, name="gpt-falesny")

"""Datové modely; třídy posílané modelům jako schéma nemají výchozí hodnoty ani omezení rozsahu."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from refiner.konfigurace import KriteriumProfilu


class Nalezitost(BaseModel):
    id: str
    text: str
    citace: str


class VystupNalezitosti(BaseModel):
    nalezitosti: list[Nalezitost]


class Kriterium(BaseModel):
    id: str
    nazev: str
    popis: str
    vaha: float
    skupina: Literal["A", "B"]


def sestav_kriteria(nalezitosti: list[Nalezitost], kriteria_profilu: list[KriteriumProfilu]) -> list[Kriterium]:
    """Skupina A z náležitostí (váha 1), pak skupina B z profilu."""
    a = [Kriterium(id=n.id, nazev=n.text, popis=n.citace, vaha=1, skupina="A") for n in nalezitosti]
    b = [Kriterium(id=k.id, nazev=k.nazev, popis=k.popis, vaha=k.vaha, skupina="B") for k in kriteria_profilu]
    return a + b


class SkoreKriteria(BaseModel):
    id: str
    skore: float
    zduvodneni: str
    dukaz: str


class VymyslenyFakt(BaseModel):
    citace: str
    proc: str


class TvrzeniKOvereni(BaseModel):
    citace: str
    proc: str


class Navrh(BaseModel):
    id: str
    kriterium: str
    misto: str
    problem: str
    navrh: str
    priorita: Literal["vysoka", "stredni", "nizka"]


class Hodnoceni(BaseModel):
    kriteria: list[SkoreKriteria]
    vymyslena_fakta: list[VymyslenyFakt]
    tvrzeni_k_overeni: list[TvrzeniKOvereni]
    navrhy: list[Navrh]
    celkovy_komentar: str


class Rozhodnuti(BaseModel):
    id_navrhu: str
    opora: str
    predpoklad: str
    dusledek: str
    rozhodnuti: Literal["prijato", "castecne", "odmitnuto"]
    zduvodneni: str
    jak_zapracovat: str


class Posouzeni(BaseModel):
    rozhodnuti: list[Rozhodnuti]
    shrnuti: str


class VysledekSkore(BaseModel):
    a: float
    b: float
    c: float
    celkem: float
    cil_splnen: bool
    duvody_nesplneni: list[str]


class Spotreba(BaseModel):
    """Spotřeba tokenů jednoho volání (neposílá se modelu, výchozí hodnoty jsou v pořádku).

    Anthropic: `vstup` nezahrnuje čtení ani zápis cache. OpenAI: `cache_cteni` je podmnožina
    `vstup`, `cache_zapis` je vždy 0.
    """

    krok: str
    model: str
    vstup: int
    vystup: int
    cache_cteni: int = 0
    cache_zapis: int = 0

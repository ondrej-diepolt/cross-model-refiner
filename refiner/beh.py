"""Složka běhu: číslované kroky, stav v data/beh.json a obnovení přerušeného běhu."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel

from refiner.data import Spotreba, VysledekSkore
from refiner.input import slug

SLOZKA_KONFIGURACE = "data/konfigurace"
_STAV_SOUBOR = "data/beh.json"

T = TypeVar("T", bound=BaseModel)


class ZaznamKroku(BaseModel):
    cislo: int
    soubor: str
    data: str | None = None


class StavBehu(BaseModel):
    vstup: str
    profil: str
    vytvoreno: datetime
    # Ukázkový běh (--nanecisto, falešné modely). Starší běhy pole nemají → ostrý běh.
    nanecisto: bool = False
    ukonceno: datetime | None = None
    stav: Literal["bezi", "dokoncen", "prerusen"] = "bezi"
    duvod_ukonceni: str | None = None
    chyba: str | None = None
    finalni_verze: int | None = None
    kroky: dict[str, ZaznamKroku] = {}
    skore: dict[str, VysledekSkore] = {}
    spotreba: list[Spotreba] = []
    varovani: list[str] = []


class Beh:
    def __init__(self, slozka: Path, stav: StavBehu):
        self.slozka = slozka
        self.stav = stav

    @classmethod
    def novy(cls, output: Path, nazev_vstupu: str, profil: str, ted: datetime,
             nanecisto: bool = False) -> Beh:
        zaklad = f"{ted:%Y-%m-%d_%H%M}_{slug(Path(nazev_vstupu).stem)}"
        slozka = output / zaklad
        n = 2
        while slozka.exists():
            slozka = output / f"{zaklad}_{n}"
            n += 1
        (slozka / "data").mkdir(parents=True)
        beh = cls(slozka, StavBehu(vstup=nazev_vstupu, profil=profil, vytvoreno=ted,
                                   nanecisto=nanecisto))
        beh.uloz()
        return beh

    @classmethod
    def otevri(cls, slozka: Path) -> Beh:
        text = (slozka / _STAV_SOUBOR).read_text(encoding="utf-8")
        return cls(slozka, StavBehu.model_validate_json(text))

    def uloz(self) -> None:
        cil = self.slozka / _STAV_SOUBOR
        tmp = cil.with_name(cil.name + ".tmp")
        tmp.write_text(self.stav.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, cil)

    def _dalsi_cislo(self) -> int:
        return max((z.cislo for z in self.stav.kroky.values()), default=0) + 1

    def zapis(self, krok: str, nazev: str, obsah: str, data: BaseModel | None = None) -> Path:
        cislo = self._dalsi_cislo()
        soubor = f"{cislo:02d}_{nazev}"
        cesta = self.zapis_pevny(soubor, obsah)
        rel_data = None
        if data is not None:
            rel_data = f"data/{cislo:02d}_{Path(nazev).stem}.json"
            self.zapis_pevny(rel_data, data.model_dump_json(indent=2))
        self.stav.kroky[krok] = ZaznamKroku(cislo=cislo, soubor=soubor, data=rel_data)
        self.uloz()
        return cesta

    def zapis_k(self, krok: str, nazev: str, obsah: str) -> Path:
        cislo = self.stav.kroky[krok].cislo
        return self.zapis_pevny(f"{cislo:02d}_{nazev}", obsah)

    def zapis_pevny(self, relativni_cesta: str, obsah: str | bytes) -> Path:
        cesta = self.slozka / relativni_cesta
        cesta.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(obsah, bytes):
            cesta.write_bytes(obsah)
        else:
            cesta.write_text(obsah, encoding="utf-8")
        return cesta

    def hotovo(self, krok: str) -> bool:
        return krok in self.stav.kroky

    def text(self, krok: str) -> str:
        return (self.slozka / self.stav.kroky[krok].soubor).read_text(encoding="utf-8")

    def data(self, krok: str, typ: type[T]) -> T:
        rel = self.stav.kroky[krok].data
        if rel is None:
            raise KeyError(f"Krok {krok} nemá uložená data")
        return typ.model_validate_json((self.slozka / rel).read_text(encoding="utf-8"))

    def pridej_spotrebu(self, polozky: list[Spotreba]) -> None:
        self.stav.spotreba.extend(polozky)
        self.uloz()

    def pridej_varovani(self, text: str) -> None:
        self.stav.varovani.append(text)
        self.uloz()

    def uloz_skore(self, cislo: int, skore: VysledekSkore) -> None:
        self.stav.skore[str(cislo)] = skore
        self.uloz()

    def ukonci(
        self,
        stav: Literal["dokoncen", "prerusen"],
        duvod: str | None = None,
        chyba: str | None = None,
        finalni_verze: int | None = None,
    ) -> None:
        self.stav.stav = stav
        self.stav.duvod_ukonceni = duvod
        self.stav.chyba = chyba
        self.stav.finalni_verze = finalni_verze
        self.stav.ukonceno = datetime.now()
        self.uloz()

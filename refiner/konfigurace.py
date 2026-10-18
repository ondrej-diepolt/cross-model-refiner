"""Načítání a validace YAML konfigurace (nastavení, profil dokumentu, kritéria k poptávce)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

TOLERANCE_SOUCTU = 1e-6


class ChybaKonfigurace(Exception):
    """Chyba v konfiguraci; zpráva je česky a obsahuje soubor, řádek a cestu k položce."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KriteriumProfilu(_Model):
    id: str
    nazev: str
    popis: str
    vaha: float = Field(gt=0)


class Profil(_Model):
    nazev: str
    typ_dokumentu: str
    pokyny_struktura: str
    kriteria: list[KriteriumProfilu]


# Povolené hodnoty effortu podle typů SDK (ověřeno v anthropic 1.15.0: OutputConfigParam.effort;
# openai 3.33.0: shared.ReasoningEffort). Překlep tak selže už při načtení konfigurace.
EffortClaude = Literal["low", "medium", "high", "xhigh", "max"]
EffortGpt = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]


class NastaveniClaude(_Model):
    model: str
    effort: EffortClaude
    effort_extrakce: EffortClaude
    max_tokens_text: int
    max_tokens_json: int
    fallback: bool


class NastaveniGpt(_Model):
    model: str
    effort: EffortGpt
    max_output_tokens: int


EffortCodex = Literal["low", "medium", "high", "xhigh", "max"]


class NastaveniClaudeCli(_Model):
    model: str = "claude-opus-5-5"
    effort: EffortClaude = "high"
    effort_extrakce: EffortClaude = "medium"
    prikaz: str | None = None


class NastaveniCodex(_Model):
    model: str = "gpt-6-astra"
    effort: EffortCodex = "high"
    prikaz: str | None = None


class NastaveniPredplatneho(_Model):
    claude: NastaveniClaudeCli = Field(default_factory=NastaveniClaudeCli)
    codex: NastaveniCodex = Field(default_factory=NastaveniCodex)


class NastaveniModelu(_Model):
    claude: NastaveniClaude
    gpt: NastaveniGpt
    max_retries: int
    timeout_s: float
    rezim: Literal["predplatne", "api"] = "predplatne"
    predplatne: NastaveniPredplatneho = Field(default_factory=NastaveniPredplatneho)

    @model_validator(mode="after")
    def _effort_extrakce_podle_rezimu(self) -> "NastaveniModelu":
        # kroky.py čte effort_extrakce z oddílu claude; v režimu predplatne platí hodnota z oddílu predplatne.
        if self.rezim == "predplatne":
            self.claude = self.claude.model_copy(
                update={"effort_extrakce": self.predplatne.claude.effort_extrakce})
        return self


class NastaveniSmycky(_Model):
    cilove_skore: float
    max_revizi: int = Field(ge=0)
    min_nalezitost: float
    max_navrhu: int = Field(ge=1)


class Cena(_Model):
    """Cena v USD za 1 milion tokenů."""

    vstup: float
    vystup: float


class Nastaveni(_Model):
    modely: NastaveniModelu
    smycka: NastaveniSmycky
    vahy_skupin: dict[Literal["A", "B", "C"], float]
    vychozi_profil: str
    ceny_usd_za_milion: dict[str, Cena]


class KriteriaKPoptavce(_Model):
    kriteria_navic: list[KriteriumProfilu] = []
    vahy: dict[str, float] = {}


@dataclass(frozen=True)
class Konfigurace:
    nastaveni: Nastaveni
    profil: Profil
    profil_nazev: str
    kriteria_profilu: list[KriteriumProfilu]


# ---------------------------------------------------------------- pomocné funkce

def _chyba(soubor: Path, radek: int | None, cesta: str, text: str) -> ChybaKonfigurace:
    cast_radek = f", řádek {radek}" if radek else ""
    cast_cesta = f"{cesta}: " if cesta else ""
    return ChybaKonfigurace(f"{soubor.name}{cast_radek}: {cast_cesta}{text}")


def _radek_uzlu(koren: yaml.Node | None, loc: tuple) -> int | None:
    """Řádek (od 1) uzlu určeného cestou; když cesta nejde celá, nejbližšího nadřazeného."""
    uzel = koren
    if uzel is None:
        return None
    for klic in loc:
        if isinstance(uzel, yaml.MappingNode):
            dalsi = next((v for k, v in uzel.value if k.value == klic), None)
        elif isinstance(uzel, yaml.SequenceNode) and isinstance(klic, int) and klic < len(uzel.value):
            dalsi = uzel.value[klic]
        else:
            dalsi = None
        if dalsi is None:
            break
        uzel = dalsi
    return uzel.start_mark.line + 1


def _nacti_yaml(soubor: Path) -> tuple[object, yaml.Node | None]:
    try:
        text = soubor.read_text(encoding="utf-8")
    except OSError as e:
        raise ChybaKonfigurace(f"{soubor.name}: soubor nelze přečíst ({e.strerror or e})") from e
    try:
        data = yaml.safe_load(text)
        koren = yaml.compose(text)
    except yaml.YAMLError as e:
        znacka = getattr(e, "problem_mark", None)
        radek = znacka.line + 1 if znacka else None
        problem = getattr(e, "problem", None) or str(e)
        raise _chyba(soubor, radek, "", f"neplatný YAML ({problem})") from e
    return data, koren


def _cesky(err: dict) -> str:
    typ = err["type"]
    if typ == "missing":
        return "chybí povinná položka"
    if typ in ("float_parsing", "float_type", "int_parsing", "int_type", "int_from_float"):
        return f"musí být číslo, je ‚{err.get('input')}‘"
    if typ == "extra_forbidden":
        return "neznámá položka (překlep?)"
    if typ == "greater_than":
        return f"musí být větší než {err['ctx']['gt']}"
    if typ == "greater_than_equal":
        return f"musí být alespoň {err['ctx']['ge']}"
    if typ == "literal_error":
        moznosti = str(err["ctx"]["expected"]).replace(" or ", " nebo ")
        return f"‚{err.get('input')}‘ není povolená hodnota, musí být jedna z: {moznosti}"
    return err["msg"]


def _validuj(model: type[_Model], soubor: Path):
    data, koren = _nacti_yaml(soubor)
    if data is None:
        data = {}
    try:
        return model.model_validate(data), koren
    except ValidationError as e:
        err = e.errors()[0]
        loc = tuple(err["loc"])
        cesta = ".".join(str(c) for c in loc)
        if err["type"] == "extra_forbidden" and loc:
            cesta = ".".join(str(c) for c in loc)
        raise _chyba(soubor, _radek_uzlu(koren, loc), cesta, _cesky(err)) from e


def _zkontroluj_id(kriteria: list[KriteriumProfilu], soubor: Path, koren, cesta: str) -> None:
    videna: set[str] = set()
    for i, k in enumerate(kriteria):
        radek = _radek_uzlu(koren, (cesta, i, "id") if cesta else (i, "id"))
        if k.id.upper().startswith("N"):
            raise _chyba(soubor, radek, f"{cesta}.{i}.id", f"ID ‚{k.id}‘ nesmí začínat písmenem N (vyhrazeno pro náležitosti)")
        if k.id in videna:
            raise _chyba(soubor, radek, f"{cesta}.{i}.id", f"duplicitní ID kritéria ‚{k.id}‘")
        videna.add(k.id)


# ---------------------------------------------------------------- veřejné rozhraní

def nacti_nastaveni(nastaveni: Path) -> Nastaveni:
    """Načte a zkontroluje samotný nastaveni.yaml (bez profilu)."""
    nast, koren_n = _validuj(Nastaveni, nastaveni)
    soucet = sum(nast.vahy_skupin.values())
    if abs(soucet - 1.0) > TOLERANCE_SOUCTU or set(nast.vahy_skupin) != {"A", "B", "C"}:
        raise _chyba(
            nastaveni,
            _radek_uzlu(koren_n, ("vahy_skupin",)),
            "vahy_skupin",
            f"váhy skupin A, B, C musí mít součet 1, je {soucet:g}",
        )
    return nast


def nacti_konfiguraci(nastaveni: Path, profil: Path, kriteria: Path | None = None) -> Konfigurace:
    nast = nacti_nastaveni(nastaveni)

    prof, koren_p = _validuj(Profil, profil)
    _zkontroluj_id(prof.kriteria, profil, koren_p, "kriteria")
    sloucena = list(prof.kriteria)

    if kriteria is not None:
        kk, koren_k = _validuj(KriteriaKPoptavce, kriteria)
        _zkontroluj_id(kk.kriteria_navic, kriteria, koren_k, "kriteria_navic")
        ids = {k.id for k in prof.kriteria}
        for i, k in enumerate(kk.kriteria_navic):
            if k.id in ids:
                raise _chyba(kriteria, _radek_uzlu(koren_k, ("kriteria_navic", i, "id")),
                             f"kriteria_navic.{i}.id", f"duplicitní ID kritéria ‚{k.id}‘")
        sloucena += kk.kriteria_navic
        ids = {k.id for k in sloucena}
        for id_, vaha in kk.vahy.items():
            radek = _radek_uzlu(koren_k, ("vahy", id_))
            if id_ not in ids:
                raise _chyba(kriteria, radek, f"vahy.{id_}",
                             f"neznámé ID kritéria ‚{id_}‘ (dostupná: {', '.join(sorted(ids))})")
            if vaha <= 0:
                raise _chyba(kriteria, radek, f"vahy.{id_}", "musí být větší než 0")
        sloucena = [k.model_copy(update={"vaha": kk.vahy.get(k.id, k.vaha)}) for k in sloucena]

    return Konfigurace(nast, prof, profil.stem, sloucena)


def cesta_kriterii_k_poptavce(vstup: Path) -> Path | None:
    cesta = vstup.with_name(vstup.stem + ".kriteria.yaml")
    return cesta if cesta.exists() else None


def dostupne_profily(slozka: Path) -> list[str]:
    return sorted(p.stem for p in slozka.glob("*.yaml"))

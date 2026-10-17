"""Kroky smyčky: sestavení promptů z prompty/*.md, volání modelů, validace výstupů a jedna oprava."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import TypeVar

from refiner.data import (
    Hodnoceni,
    Kriterium,
    Nalezitost,
    Navrh,
    Posouzeni,
    Rozhodnuti,
    VystupNalezitosti,
    sestav_kriteria,
)
from refiner.konfigurace import ChybaKonfigurace, Konfigurace
from refiner.modely.chyby import ChybaModelu, Sluzba
from refiner.modely.rozhrani import Model

T = TypeVar("T")

PRAZDNE_PODKLADY = "(Profil firmy nebyl dodán – všechna fakta o dodavateli označ [DOPLNIT: …].)"
ZADNE_ODMITNUTE = "(žádné)"
MIN_POMER_DELKY = 0.7
PORADI_PRIORIT = {"vysoka": 0, "stredni": 1, "nizka": 2}
SLOVA_ZKRACENI = ("zkrát", "odstran")

ZADANI_NALEZITOSTI = "Vypiš povinné náležitosti z poptávky výše podle pokynů."
ZADANI_NAVRH = "Napiš dokument podle pokynů výše."


@dataclass(frozen=True)
class Zdroje:
    poptavka: str
    podklady: str
    konfigurace: Konfigurace
    prompty: Path


# ---------------------------------------------------------------- prompty

def vykresli_prompt(slozka: Path, nazev: str, **promenne: str) -> str:
    soubor = slozka / (nazev if nazev.endswith(".md") else f"{nazev}.md")
    try:
        text = soubor.read_text(encoding="utf-8")
    except OSError as e:
        raise ChybaKonfigurace(f"{soubor.name}: prompt nelze přečíst ({e.strerror or e})") from e
    try:
        return Template(text).substitute(promenne)
    except KeyError as e:
        dostupne = ", ".join(sorted(promenne)) or "žádné"
        raise ChybaKonfigurace(
            f"{soubor.name}: neznámá proměnná ${{{e.args[0]}}} (dostupné proměnné: {dostupne})"
        ) from e
    except ValueError as e:
        raise ChybaKonfigurace(
            f"{soubor.name}: neplatný zápis proměnné ({e}); znak $ v textu pište jako $$"
        ) from e


def _spolecne(zdroje: Zdroje) -> dict[str, str]:
    return {
        "poptavka": zdroje.poptavka,
        "podklady": zdroje.podklady if zdroje.podklady.strip() else PRAZDNE_PODKLADY,
    }


def _text_nalezitosti(nalezitosti: list[Nalezitost]) -> str:
    return "\n".join(f"- **{n.id}** {n.text} – citace z poptávky: „{n.citace}“" for n in nalezitosti)


def _text_kriterii(kriteria: list[Kriterium]) -> str:
    radky = []
    for k in kriteria:
        if k.skupina == "A":
            radky.append(f"- **{k.id}** (A – povinná náležitost) {k.nazev}. Citace z poptávky: „{k.popis}“")
        else:
            radky.append(f"- **{k.id}** (B – obecná kvalita) {k.nazev}: {k.popis}")
    return "\n".join(radky)


def _text_odmitnutych(odmitnute: list[tuple[Navrh, Rozhodnuti]]) -> str:
    if not odmitnute:
        return ZADNE_ODMITNUTE
    bloky = []
    for n, r in odmitnute:
        bloky.append(
            f"- Kritérium {n.kriterium}, místo: {n.misto}\n"
            f"  - Problém: {n.problem}\n"
            f"  - Návrh: {n.navrh}\n"
            f"  - Důvod odmítnutí: {r.zduvodneni}"
        )
    return "\n".join(bloky)


def _sekce_dokument(dokument: str) -> str:
    return f"## Dokument\n\n<dokument>\n{dokument}\n</dokument>"


def _text_navrhu(navrhy: list[Navrh]) -> str:
    return "\n\n".join(
        f"### {n.id} (kritérium {n.kriterium}, priorita {n.priorita})\n"
        f"- Místo: {n.misto}\n- Problém: {n.problem}\n- Návrh: {n.navrh}"
        for n in navrhy
    )


def _text_prijatych(hodnoceni: Hodnoceni, posouzeni: Posouzeni) -> str:
    podle_id = {n.id: n for n in hodnoceni.navrhy}
    bloky = []
    for r in prijate(posouzeni):
        stav = "přijato" if r.rozhodnuti == "prijato" else "přijato částečně"
        radky = [f"### {r.id_navrhu} ({stav})"]
        n = podle_id.get(r.id_navrhu)
        if n is not None:
            radky += [f"- Místo: {n.misto}", f"- Problém: {n.problem}", f"- Návrh hodnotitele: {n.navrh}"]
        radky.append(f"- Jak zapracovat: {r.jak_zapracovat}")
        bloky.append("\n".join(radky))
    return "\n\n".join(bloky)


def _vycisti_dokument(text: str) -> str:
    """Odstraní obal, který model občas přidá navzdory pokynům (blok kódu, značky <dokument>)."""
    t = text.strip()
    radky = t.splitlines()
    if len(radky) >= 2 and radky[0].startswith("```") and radky[-1].strip() == "```":
        t = "\n".join(radky[1:-1]).strip()
    if t.startswith("<dokument>") and t.endswith("</dokument>"):
        t = t[len("<dokument>"):-len("</dokument>")].strip()
    return t


# ---------------------------------------------------------------- volání s jednou opravou

def _sluzba(model: Model) -> Sluzba:
    return "OpenAI" if model.nazev.lower().startswith("gpt") else "Anthropic"


def _s_opravou(
    model: Model,
    zadani: str,
    zavolej: Callable[[str], T],
    zkontroluj: Callable[[T], list[str]],
    surove: Callable[[T], str],
) -> T:
    """Zavolá model nejvýš 2×; druhé volání dostane v zadání popis chyb z prvního."""
    chyby: list[str] = []
    surova: str | None = None
    for pokus in range(2):
        z = zadani if pokus == 0 else f"{zadani}\n\n## Oprava\nPředchozí odpověď byla neplatná: {'; '.join(chyby)}"
        try:
            vysledek = zavolej(z)
        except ChybaModelu as e:
            if e.druh != "nevalidni_vystup":
                raise
            chyby = [e.detail or e.hlaska]
            surova = e.surova_odpoved
            continue
        chyby = zkontroluj(vysledek)
        if not chyby:
            return vysledek
        surova = surove(vysledek)
    raise ChybaModelu("nevalidni_vystup", _sluzba(model), detail="; ".join(chyby), surova_odpoved=surova)


# ---------------------------------------------------------------- kontroly

def _cislo(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def _normalizuj(text: str) -> str:
    return " ".join(text.split())


def _rozdel_nalezitosti(
    vystup: VystupNalezitosti, poptavka: str
) -> tuple[list[Nalezitost], list[str]]:
    """Ponechá náležitosti, jejichž citace (po normalizaci bílých znaků) je doslova v poptávce."""
    text = _normalizuj(poptavka)
    platne, varovani = [], []
    for n in vystup.nalezitosti:
        if _normalizuj(n.citace) and _normalizuj(n.citace) in text:
            platne.append(n)
        else:
            varovani.append(
                f"Náležitost {n.id} („{n.text}“) byla zahozena: citace „{n.citace}“ se v poptávce nevyskytuje."
            )
    return platne, varovani


def _zkontroluj_nalezitosti(vystup: VystupNalezitosti, poptavka: str) -> list[str]:
    chyby = []
    ids = [n.id for n in vystup.nalezitosti]
    for id_ in sorted({i for i in ids if ids.count(i) > 1}):
        chyby.append(f"ID náležitosti {id_} je použito vícekrát.")
    platne, varovani = _rozdel_nalezitosti(vystup, poptavka)
    if not platne:
        chyby.append("Žádná náležitost nemá citaci, která by byla doslova v poptávce. " + " ".join(varovani))
    return chyby


def zkontroluj_hodnoceni(h: Hodnoceni, kriteria: list[Kriterium]) -> list[str]:
    chyby = []
    # spocitej() kritéria bez skóre potichu přeskočí – tato kontrola je jediná pojistka,
    # že každé kritérium ze vstupu je ohodnoceno právě jednou.
    pocty: dict[str, int] = {}
    for s in h.kriteria:
        pocty[s.id] = pocty.get(s.id, 0) + 1
    zname = {k.id for k in kriteria}
    for k in kriteria:
        pocet = pocty.get(k.id, 0)
        if pocet == 0:
            chyby.append(f"Chybí hodnocení kritéria {k.id}.")
        elif pocet > 1:
            chyby.append(f"Kritérium {k.id} je hodnoceno {pocet}×, má být právě jednou.")
    for id_ in pocty:
        if id_ not in zname:
            chyby.append(f"Neznámé kritérium {id_} (povolená: {', '.join(k.id for k in kriteria)}).")
    for s in h.kriteria:
        if not 1 <= s.skore <= 10:
            chyby.append(f"Skóre kritéria {s.id} je {_cislo(s.skore)}, musí být 1–10.")
        elif abs(s.skore * 2 - round(s.skore * 2)) > 1e-9:
            chyby.append(f"Skóre kritéria {s.id} je {_cislo(s.skore)}, musí být násobek 0,5.")
    ids = [n.id for n in h.navrhy]
    for id_ in sorted({i for i in ids if ids.count(i) > 1}):
        chyby.append(f"ID návrhu {id_} je použito vícekrát.")
    for n in h.navrhy:
        if n.kriterium not in zname:
            chyby.append(f"Návrh {n.id} odkazuje na neznámé kritérium {n.kriterium}.")
    return chyby


def zkontroluj_posouzeni(p: Posouzeni, h: Hodnoceni) -> list[str]:
    chyby = []
    pocty: dict[str, int] = {}
    for r in p.rozhodnuti:
        pocty[r.id_navrhu] = pocty.get(r.id_navrhu, 0) + 1
    navrhy = [n.id for n in h.navrhy]
    for id_ in navrhy:
        pocet = pocty.get(id_, 0)
        if pocet == 0:
            chyby.append(f"Chybí rozhodnutí k návrhu {id_}.")
        elif pocet > 1:
            chyby.append(f"K návrhu {id_} je {pocet} rozhodnutí, má být právě jedno.")
    for id_ in pocty:
        if id_ not in navrhy:
            chyby.append(f"Rozhodnutí k neznámému návrhu {id_}.")
    return chyby


def prijate(posouzeni: Posouzeni) -> list[Rozhodnuti]:
    return [r for r in posouzeni.rozhodnuti if r.rozhodnuti in ("prijato", "castecne")]


def zkontroluj_prepis(stary: str, novy: str, hodnoceni: Hodnoceni, posouzeni: Posouzeni) -> list[str]:
    if not novy.strip():
        return ["Nový dokument je prázdný."]
    chyby = []
    nove_radky = {r.rstrip() for r in novy.splitlines()}
    for radek in stary.splitlines():
        if radek.startswith("# ") and radek.rstrip() not in nove_radky:
            chyby.append(f"Z dokumentu zmizel nadpis „{radek.rstrip()}“.")
    if len(novy) < MIN_POMER_DELKY * len(stary):
        podle_id = {n.id: n for n in hodnoceni.navrhy}
        texty = []
        for r in prijate(posouzeni):
            n = podle_id.get(r.id_navrhu)
            texty.append(((n.navrh if n else "") + " " + r.jak_zapracovat).lower())
        if not any(slovo in t for t in texty for slovo in SLOVA_ZKRACENI):
            chyby.append(
                f"Dokument se zkrátil na {round(100 * len(novy) / len(stary))} % původní délky, "
                "ačkoli žádný přijatý návrh zkrácení nepožaduje. Vrať celý dokument."
            )
    return chyby


# ---------------------------------------------------------------- kroky

def extrahuj_nalezitosti(model: Model, zdroje: Zdroje) -> tuple[list[Nalezitost], list[str]]:
    instrukce = vykresli_prompt(zdroje.prompty, "nalezitosti", poptavka=zdroje.poptavka)
    effort = zdroje.konfigurace.nastaveni.modely.claude.effort_extrakce
    vystup = _s_opravou(
        model,
        ZADANI_NALEZITOSTI,
        lambda z: model.json(instrukce, z, VystupNalezitosti, krok="nalezitosti", effort=effort),
        lambda v: _zkontroluj_nalezitosti(v, zdroje.poptavka),
        lambda v: v.model_dump_json(indent=2),
    )
    return _rozdel_nalezitosti(vystup, zdroje.poptavka)


def napis_navrh(model: Model, zdroje: Zdroje, nalezitosti: list[Nalezitost]) -> str:
    konf = zdroje.konfigurace
    instrukce = vykresli_prompt(
        zdroje.prompty, "navrh",
        typ_dokumentu=konf.profil.typ_dokumentu,
        pokyny_struktura=konf.profil.pokyny_struktura,
        nalezitosti=_text_nalezitosti(nalezitosti),
        kriteria=_text_kriterii(sestav_kriteria(nalezitosti, konf.kriteria_profilu)),
        **_spolecne(zdroje),
    )
    return _s_opravou(
        model,
        ZADANI_NAVRH,
        lambda z: _vycisti_dokument(model.text(instrukce, z, krok="navrh_1")),
        lambda t: [] if t.strip() else ["Dokument je prázdný."],
        lambda t: t,
    )


def ohodnot(
    model: Model,
    zdroje: Zdroje,
    kriteria: list[Kriterium],
    dokument: str,
    odmitnute: list[tuple[Navrh, Rozhodnuti]],
    krok: str,
) -> tuple[Hodnoceni, list[str]]:
    konf = zdroje.konfigurace
    max_navrhu = konf.nastaveni.smycka.max_navrhu
    instrukce = vykresli_prompt(
        zdroje.prompty, "hodnoceni",
        typ_dokumentu=konf.profil.typ_dokumentu,
        kriteria=_text_kriterii(kriteria),
        max_navrhu=str(max_navrhu),
        odmitnute=_text_odmitnutych(odmitnute),
        **_spolecne(zdroje),
    )
    h = _s_opravou(
        model,
        _sekce_dokument(dokument),
        lambda z: model.json(instrukce, z, Hodnoceni, krok=krok),
        lambda v: zkontroluj_hodnoceni(v, kriteria),
        lambda v: v.model_dump_json(indent=2),
    )
    varovani = []
    if len(h.navrhy) > max_navrhu:
        serazene = sorted(h.navrhy, key=lambda n: PORADI_PRIORIT[n.priorita])
        ponechane, vynechane = serazene[:max_navrhu], serazene[max_navrhu:]
        varovani.append(
            f"Hodnotitel vrátil {len(h.navrhy)} návrhů, ponecháno {max_navrhu} podle priority; "
            f"vynechány: {', '.join(n.id for n in vynechane)}."
        )
        h = h.model_copy(update={"navrhy": ponechane})
    return h, varovani


def posud(
    model: Model,
    zdroje: Zdroje,
    nalezitosti: list[Nalezitost],
    dokument: str,
    hodnoceni: Hodnoceni,
    krok: str,
) -> Posouzeni:
    instrukce = vykresli_prompt(
        zdroje.prompty, "posouzeni", nalezitosti=_text_nalezitosti(nalezitosti), **_spolecne(zdroje)
    )
    zadani = f"{_sekce_dokument(dokument)}\n\n## Návrhy hodnotitele\n\n{_text_navrhu(hodnoceni.navrhy)}"
    return _s_opravou(
        model,
        zadani,
        lambda z: model.json(instrukce, z, Posouzeni, krok=krok),
        lambda v: zkontroluj_posouzeni(v, hodnoceni),
        lambda v: v.model_dump_json(indent=2),
    )


def zapracuj(
    model: Model,
    zdroje: Zdroje,
    nalezitosti: list[Nalezitost],
    dokument: str,
    hodnoceni: Hodnoceni,
    posouzeni: Posouzeni,
    krok: str,
) -> str:
    instrukce = vykresli_prompt(
        zdroje.prompty, "zapracovani", nalezitosti=_text_nalezitosti(nalezitosti), **_spolecne(zdroje)
    )
    zadani = (
        f"{_sekce_dokument(dokument)}\n\n## Přijaté návrhy k zapracování\n\n"
        f"{_text_prijatych(hodnoceni, posouzeni)}"
    )
    return _s_opravou(
        model,
        zadani,
        lambda z: _vycisti_dokument(model.text(instrukce, z, krok=krok)),
        lambda t: zkontroluj_prepis(dokument, t, hodnoceni, posouzeni),
        lambda t: t,
    )

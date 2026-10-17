"""Lidsky čitelné Markdown výstupy: náležitosti, hodnocení, posouzení."""
from __future__ import annotations

from refiner.data import Hodnoceni, Kriterium, Nalezitost, Posouzeni, VysledekSkore
from refiner.skore import format_skore

_POPISKY = {"prijato": "přijato", "castecne": "částečně", "odmitnuto": "odmítnuto"}


def bunka(text: object) -> str:
    """Text bezpečný do buňky tabulky: bez zalomení řádků a s escapovaným svislítkem."""
    return " ".join(str(text).split()).replace("|", chr(92) + "|")


def _radek(*bunky: object) -> str:
    return "| " + " | ".join(bunka(b) for b in bunky) + " |"


def nalezitosti_md(nalezitosti: list[Nalezitost], varovani: list[str]) -> str:
    r = ["# Náležitosti nabídky", "", "| ID | Náležitost | Citace z poptávky |", "|---|---|---|"]
    r += [_radek(n.id, n.text, n.citace) for n in nalezitosti]
    if varovani:
        r += ["", "## Varování", ""] + [f"- {v}" for v in varovani]
    return "\n".join(r) + "\n"


def hodnoceni_md(cislo: int, h: Hodnoceni, skore: VysledekSkore, kriteria: list[Kriterium]) -> str:
    nazvy = {k.id: k.nazev for k in kriteria}
    r = [
        f"# Hodnocení {cislo}",
        "",
        f"- Skupina A (náležitosti): {format_skore(skore.a)}",
        f"- Skupina B (kvalita): {format_skore(skore.b)}",
        f"- Skupina C (vymyšlená fakta): {format_skore(skore.c)}",
        f"- **Celkem: {format_skore(skore.celkem)}**",
        f"- Cíl splněn: {'ano' if skore.cil_splnen else 'ne'}",
    ]
    if skore.duvody_nesplneni:
        r += ["", "Důvody nesplnění:", ""] + [f"- {d}" for d in skore.duvody_nesplneni]
    r += ["", "## Kritéria", "", "| ID | Název | Skóre | Zdůvodnění | Důkaz |", "|---|---|---|---|---|"]
    r += [_radek(s.id, nazvy.get(s.id, ""), format_skore(s.skore), s.zduvodneni, s.dukaz) for s in h.kriteria]
    r += ["", "## Vymyšlená fakta", ""]
    r += [f"- {bunka(f.citace)} – {bunka(f.proc)}" for f in h.vymyslena_fakta] or ["Žádná."]
    r += ["", "## Tvrzení k ověření", ""]
    r += [f"- {bunka(t.citace)} – {bunka(t.proc)}" for t in h.tvrzeni_k_overeni] or ["Žádná."]
    r += ["", "## Návrhy", ""]
    if h.navrhy:
        r += ["| ID | Kritérium | Místo | Problém | Návrh | Priorita |", "|---|---|---|---|---|---|"]
        r += [_radek(n.id, n.kriterium, n.misto, n.problem, n.navrh, n.priorita) for n in h.navrhy]
    else:
        r.append("Žádné.")
    r += ["", "## Celkový komentář", "", h.celkovy_komentar]
    return "\n".join(r) + "\n"


def posouzeni_md(cislo: int, h: Hodnoceni, p: Posouzeni) -> str:
    navrhy = {n.id: n for n in h.navrhy}
    pocet = {k: sum(1 for x in p.rozhodnuti if x.rozhodnuti == k) for k in _POPISKY}
    r = [
        f"# Posouzení návrhů z hodnocení {cislo}",
        "",
        f"Přijato: {pocet['prijato']} · Částečně: {pocet['castecne']} · Odmítnuto: {pocet['odmitnuto']}",
        "",
        p.shrnuti,
    ]
    for x in p.rozhodnuti:
        n = navrhy.get(x.id_navrhu)
        r += ["", f"## Návrh {x.id_navrhu}", ""]
        if n:
            r += [f"- Místo: {bunka(n.misto)}", f"- Znění návrhu: {bunka(n.navrh)}"]
        r += [
            f"- Opora: {x.opora}",
            f"- Předpoklad: {x.predpoklad}",
            f"- Důsledek: {x.dusledek}",
            f"- **Rozhodnutí: {_POPISKY[x.rozhodnuti]}**",
            f"- Zdůvodnění: {x.zduvodneni}",
            f"- Jak zapracovat: {x.jak_zapracovat}",
        ]
    return "\n".join(r) + "\n"

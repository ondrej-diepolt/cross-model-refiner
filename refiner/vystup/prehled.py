"""Souhrnný přehled běhu jako statické HTML (design kap. 7); vychází jen ze stavu a dat běhu."""
from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from refiner.beh import Beh
from refiner.data import Hodnoceni, Posouzeni, Spotreba, VystupNalezitosti, sestav_kriteria
from refiner.fakta import najdi_placeholdery, podezrele_udaje
from refiner.konfigurace import Konfigurace
from refiner.skore import format_skore

_SABLONY = Path(__file__).parent / "sablony"

_DRUHY = {
    "castka": "Částky", "ico": "IČO", "email": "E-maily", "telefon": "Telefony",
    "jmeno": "Jména", "url": "Odkazy",
}
_NAZVY_KROKU = {"poptavka": "Poptávka", "nalezitosti": "Náležitosti z poptávky"}


def _trida_skore(x: float) -> str:
    if x < 7:
        return "s-cervena"
    if x < 9:
        return "s-oranzova"
    return "s-zelena"


def _desetinne(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def _popis_kroku(klic: str) -> str:
    if klic in _NAZVY_KROKU:
        return _NAZVY_KROKU[klic]
    m = re.fullmatch(r"(navrh|hodnoceni|posouzeni)_(\d+)", klic)
    if not m:
        return klic
    druh, n = m.group(1), m.group(2)
    return {"navrh": f"Návrh, verze {n}", "hodnoceni": f"Hodnocení {n}", "posouzeni": f"Posouzení {n}"}[druh]


def _doba(beh: Beh) -> str:
    konec = beh.stav.ukonceno
    if konec is None:
        return "neukončeno"
    sekundy = max(0, int((konec - beh.stav.vytvoreno).total_seconds()))
    minut, s = divmod(sekundy, 60)
    return f"{minut} min {s} s"


def _nacti_hodnoceni(beh: Beh) -> dict[int, Hodnoceni]:
    vysledek: dict[int, Hodnoceni] = {}
    for klic, z in beh.stav.kroky.items():
        m = re.fullmatch(r"hodnoceni_(\d+)", klic)
        if m and z.data:
            vysledek[int(m.group(1))] = beh.data(klic, Hodnoceni)
    return dict(sorted(vysledek.items()))


def _nacti_posouzeni(beh: Beh) -> dict[int, Posouzeni]:
    vysledek: dict[int, Posouzeni] = {}
    for klic, z in beh.stav.kroky.items():
        m = re.fullmatch(r"posouzeni_(\d+)", klic)
        if m and z.data:
            vysledek[int(m.group(1))] = beh.data(klic, Posouzeni)
    return vysledek


def _bunka(hodnota: float | None, titulek: str = "") -> dict:
    if hodnota is None:
        return {"text": "–", "trida": "", "titulek": titulek}
    return {"text": format_skore(hodnota), "trida": _trida_skore(hodnota), "titulek": titulek}


def _tabulka(beh: Beh, konf: Konfigurace, hodnoceni: dict[int, Hodnoceni], cisla: list[int]) -> list[dict]:
    """Řádky tabulky skóre; vše se hledá podle čísla hodnocení (ID se v kolech opakují)."""
    if not cisla:
        return []
    kriteria = []
    if beh.hotovo("nalezitosti") and beh.stav.kroky["nalezitosti"].data:
        kriteria = sestav_kriteria(beh.data("nalezitosti", VystupNalezitosti).nalezitosti,
                                   konf.kriteria_profilu)
    skore = beh.stav.skore

    def ze_skore(atribut: str) -> list[dict]:
        return [_bunka(getattr(skore[str(c)], atribut) if str(c) in skore else None) for c in cisla]

    radky: list[dict] = []
    for skupina, atribut, nazev in (("A", "a", "Skupina A – průměr náležitostí"),
                                    ("B", "b", "Skupina B – vážený průměr")):
        for k in (x for x in kriteria if x.skupina == skupina):
            bunky = []
            for c in cisla:
                h = hodnoceni.get(c)
                s = next((x for x in h.kriteria if x.id == k.id), None) if h else None
                bunky.append(_bunka(s.skore if s else None, s.zduvodneni if s else ""))
            radky.append({"typ": "kriterium", "id": k.id, "nazev": k.nazev, "bunky": bunky})
        if kriteria:
            radky.append({"typ": "souhrn", "id": skupina, "nazev": nazev, "bunky": ze_skore(atribut)})
    radky.append({"typ": "souhrn", "id": "C", "nazev": "Skupina C – bez vymyšlených faktů",
                  "bunky": ze_skore("c")})
    radky.append({"typ": "celkem", "id": "", "nazev": "Celkem", "bunky": ze_skore("celkem")})
    return radky


def _cena(spotreba: list[Spotreba], konf: Konfigurace) -> dict:
    ceny = konf.nastaveni.ceny_usd_za_milion
    souhrn: dict[str, dict] = {}
    for s in spotreba:
        r = souhrn.setdefault(s.model, {"model": s.model, "vstup": 0, "vystup": 0})
        r["vstup"] += s.vstup
        r["vystup"] += s.vystup
    celkem = 0.0
    neznama = False
    radky = []
    for r in souhrn.values():
        c = ceny.get(r["model"])
        if c is None:
            neznama = True
            cena_txt = "cena neznámá"
        else:
            cena = (r["vstup"] * c.vstup + r["vystup"] * c.vystup) / 1_000_000
            celkem += cena
            cena_txt = f"{_desetinne(cena)} USD"
        radky.append({**r, "cena": cena_txt})
    return {
        "radky": radky, "celkem": _desetinne(celkem), "neznama": neznama,
        "vstup": sum(r["vstup"] for r in radky), "vystup": sum(r["vystup"] for r in radky),
    }


def _kroky(beh: Beh) -> list[dict]:
    """Časová osa; odkazy vznikají jen z názvů souborů zapsaných kroků."""
    vysledek = []
    for klic, z in sorted(beh.stav.kroky.items(), key=lambda kv: kv[1].cislo):
        odkazy = [{"soubor": z.soubor, "popis": z.soubor}]
        if re.fullmatch(r"navrh_([2-9]|\d{2,})", klic):
            zmeny = f"{Path(z.soubor).stem}_zmeny.html"
            if (beh.slozka / zmeny).exists():
                odkazy.append({"soubor": zmeny, "popis": "změny proti předchozí verzi"})
        vysledek.append({"cislo": z.cislo, "popis": _popis_kroku(klic), "odkazy": odkazy})
    return vysledek


def vytvor_prehled(beh: Beh, konfigurace: Konfigurace) -> Path:
    stav = beh.stav
    hodnoceni = _nacti_hodnoceni(beh)
    posouzeni = _nacti_posouzeni(beh)
    skore = {int(k): v for k, v in stav.skore.items()}
    cisla = sorted(set(hodnoceni) | set(skore))
    nastaveni = konfigurace.nastaveni

    finalni = stav.finalni_verze if stav.stav == "dokoncen" else None
    fin_skore = skore.get(finalni) if finalni is not None else None
    posledni = cisla[-1] if cisla else None

    duvod = None
    if stav.stav == "dokoncen":
        if stav.duvod_ukonceni == "cil_splnen":
            cil = format_skore(nastaveni.smycka.cilove_skore)
            duvod = f"Cíl splněn (skóre {format_skore(fin_skore.celkem) if fin_skore else '?'} ≥ {cil})"
        elif stav.duvod_ukonceni == "limit_revizi":
            duvod = f"Vyčerpán limit {nastaveni.smycka.max_revizi} revizí"
        elif stav.duvod_ukonceni == "zadna_zmena":
            duvod = "Hodnotitel nenavrhl nic, co by prošlo posouzením"
        else:
            duvod = stav.duvod_ukonceni or "Běh skončil"

    vysvetleni = None
    if finalni is not None and fin_skore and posledni is not None and finalni != posledni \
            and posledni in skore:
        vysvetleni = (
            f"Finální je verze {finalni}, ne poslední verze {posledni}: verze {finalni} má vyšší skóre "
            f"({format_skore(fin_skore.celkem)}) než verze {posledni} ({format_skore(skore[posledni].celkem)})."
        )

    placeholdery: list[str] = []
    podezrele: list[dict] = []
    tvrzeni: list = []
    if finalni is not None:
        klic = f"navrh_{finalni}"
        if beh.hotovo(klic) and (beh.slozka / beh.stav.kroky[klic].soubor).exists():
            dokument = beh.text(klic)
            placeholdery = najdi_placeholdery(dokument)
            zdroje = beh.text("poptavka") if beh.hotovo("poptavka") else ""
            podklady = beh.slozka / "data" / "podklady.md"
            if podklady.exists():
                zdroje += "\n" + podklady.read_text(encoding="utf-8")
            skupiny: dict[str, list[str]] = {}
            for u in podezrele_udaje(dokument, zdroje):
                skupiny.setdefault(u.druh, []).append(u.hodnota)
            podezrele = [{"druh": _DRUHY[d], "hodnoty": v} for d, v in skupiny.items()]
        if finalni in hodnoceni:
            tvrzeni = hodnoceni[finalni].tvrzeni_k_overeni

    # Statistika návrhů po kolech: ID návrhů se opakují v každém kole.
    kola = []
    soucet = {"navrhu": 0, "prijato": 0, "castecne": 0, "odmitnuto": 0}
    for c, h in hodnoceni.items():
        p = posouzeni.get(c)
        radek = {"kolo": c, "navrhu": len(h.navrhy), "prijato": 0, "castecne": 0, "odmitnuto": 0,
                 "posouzeno": p is not None}
        if p:
            for r in p.rozhodnuti:
                radek[r.rozhodnuti] += 1
        for k in soucet:
            soucet[k] += radek[k]
        kola.append(radek)

    nazev_finalu = f"FINALNI_{konfigurace.profil_nazev}"
    soubory = [{"soubor": f"{nazev_finalu}{pripona}",
                "existuje": (beh.slozka / f"{nazev_finalu}{pripona}").exists()}
               for pripona in (".docx", ".md")]

    env = Environment(loader=FileSystemLoader(_SABLONY), autoescape=True)
    html = env.get_template("prehled.html.j2").render(
        stav=stav, duvod=duvod, vysvetleni=vysvetleni, finalni=finalni,
        fin_skore=format_skore(fin_skore.celkem) if fin_skore else None,
        soubory=soubory, cisla=cisla, tabulka=_tabulka(beh, konfigurace, hodnoceni, cisla),
        komentare=[(c, h.celkovy_komentar) for c, h in hodnoceni.items()],
        placeholdery=placeholdery, tvrzeni=tvrzeni, podezrele=podezrele,
        kroky=_kroky(beh), kola=kola, soucet=soucet, cena=_cena(stav.spotreba, konfigurace),
        doba=_doba(beh), vytvoreno=f"{stav.vytvoreno:%d. %m. %Y %H:%M}",
        profil=konfigurace.profil_nazev,
    )
    return beh.zapis_pevny("prehled.html", html)

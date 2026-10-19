"""Porovnání dokončeného běhu s ručně dotaženou referenční nabídkou (design kap. 11).

Referenci vidí jen hodnotitel; pisatel ji nikdy nedostane (generování nečte examples/).
Výstupy ve složce běhu nemají čísla kroků a opakované porovnání je přepíše:
porovnani.html, data/porovnani.json, data/porovnani_kalibrace.json. Formulář
porovnani_formular.md se vytvoří jen poprvé, aby se nepřepsaly odpovědi konzultanta.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal, TypeVar

from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

from refiner.beh import Beh
from refiner.data import (
    Hodnoceni,
    Kriterium,
    SkoreKriteria,
    VysledekSkore,
    VystupNalezitosti,
    sestav_kriteria,
)
from refiner.kroky import (
    Zdroje,
    ohodnot,
    s_opravou,
    sekce_dokument,
    spolecne_promenne,
    text_kriterii,
    vykresli_prompt,
)
from refiner.models.interface import Model
from refiner.skore import format_skore, spocitej
from refiner.input import SUPPORTED_EXTENSIONS, InputError, read_as_markdown, find_inputs

_SABLONY = Path(__file__).parent / "vystup" / "sablony"

PROMPTY_POROVNANI = ("porovnani_kriteria", "porovnani_prvky", "porovnani_pokryti")
FORMULAR = "porovnani_formular.md"
OTAZKY_FORMULARE = (
    "Odeslal bych to po doplnění placeholderů?",
    "Kolik minut práce do odeslatelné verze?",
    "Věcné chyby?",
    "Co chybí?",
    "Co je lepší než v referenci?",
)

ZADANI_PRVKY = "Vypiš obsahové prvky dokumentu níže podle pokynů."
_PORADI_POKRYTI = {"chybi": 0, "castecne": 1, "je": 2}

Verdikt = Literal["generovana", "reference", "nerozhodne"]
T = TypeVar("T", bound=BaseModel)


# ---------------------------------------------------------------- schémata (posílají se modelu)

class SrovnaniKriteria(BaseModel):
    id: str
    lepsi: Literal["A", "B", "stejne"]
    zduvodneni: str


class Srovnani(BaseModel):
    kriteria: list[SrovnaniKriteria]


class PrvekReference(BaseModel):
    id: str
    popis: str


class SeznamPrvku(BaseModel):
    prvky: list[PrvekReference]


class PokrytiPrvku(BaseModel):
    id: str
    stav: Literal["je", "castecne", "chybi"]
    komentar: str


class Pokryti(BaseModel):
    polozky: list[PokrytiPrvku]


class VysledekPorovnani(BaseModel):
    skore_reference: VysledekSkore
    skore_generovane: VysledekSkore
    srovnani: dict[str, Verdikt]
    zduvodneni: dict[str, list[str]]
    prvky: list[PrvekReference]
    pokryti: list[PokrytiPrvku]


# ---------------------------------------------------------------- čisté funkce

_S1: dict[str, Verdikt | None] = {"A": "generovana", "B": "reference", "stejne": None}
_S2: dict[str, Verdikt | None] = {"A": "reference", "B": "generovana", "stejne": None}


def zkombinuj_srovnani(s1: Srovnani, s2: Srovnani) -> dict[str, Verdikt]:
    """V `s1` je A = generovaná, B = reference; v `s2` naopak. Shoda → vítěz, jinak nerozhodně."""
    druhe = {x.id: _S2[x.lepsi] for x in s2.kriteria}
    vysledek: dict[str, Verdikt] = {}
    for x in s1.kriteria:
        prvni = _S1[x.lepsi]
        vysledek[x.id] = prvni if prvni is not None and prvni == druhe.get(x.id) else "nerozhodne"
    return vysledek


def najdi_referenci(koren: Path) -> Path:
    """Jediný podporovaný soubor (DOCX, MD, TXT) v koren/examples/."""
    slozka = Path(koren) / "examples"
    soubory = find_inputs(slozka) if slozka.is_dir() else []
    if len(soubory) == 1:
        return soubory[0]
    raise InputError(
        f"Ve složce examples/ má být právě jedna referenční nabídka (DOCX, MD nebo TXT), "
        f"nalezeno: {len(soubory)}. Jinak použijte --reference SOUBOR."
    )


def nacti_referenci(cesta: Path) -> str:
    cesta = Path(cesta)
    if not cesta.is_file():
        raise InputError(f"Referenční soubor {cesta} neexistuje.")
    if cesta.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise InputError(f"Referenční soubor {cesta.name} musí být DOCX, MD nebo TXT.")
    return read_as_markdown(cesta)


# ---------------------------------------------------------------- kontroly odpovědí

def _pocty(ids: list[str]) -> dict[str, int]:
    pocty: dict[str, int] = {}
    for i in ids:
        pocty[i] = pocty.get(i, 0) + 1
    return pocty


def _kazde_prave_jednou(ids: list[str], ocekavana: list[str], co: str) -> list[str]:
    pocty = _pocty(ids)
    chyby = []
    for id_ in ocekavana:
        pocet = pocty.get(id_, 0)
        if pocet == 0:
            chyby.append(f"Chybí {co} {id_}.")
        elif pocet > 1:
            chyby.append(f"{co[:1].upper()}{co[1:]} {id_} je uvedeno {pocet}×, má být právě jednou.")
    for id_ in pocty:
        if id_ not in ocekavana:
            chyby.append(f"Neznámé ID {id_} (povolená: {', '.join(ocekavana)}).")
    return chyby


def zkontroluj_srovnani(s: Srovnani, kriteria: list[Kriterium]) -> list[str]:
    return _kazde_prave_jednou([x.id for x in s.kriteria], [k.id for k in kriteria], "srovnání kritéria")


def zkontroluj_prvky(s: SeznamPrvku) -> list[str]:
    if not s.prvky:
        return ["Seznam prvků je prázdný."]
    ids = [p.id for p in s.prvky]
    return [f"ID prvku {i} je použito vícekrát." for i in sorted({i for i in ids if ids.count(i) > 1})]


def zkontroluj_pokryti(p: Pokryti, prvky: list[PrvekReference]) -> list[str]:
    return _kazde_prave_jednou([x.id for x in p.polozky], [x.id for x in prvky], "pokrytí prvku")


# ---------------------------------------------------------------- texty pro model

def _zadani_srovnani(a: str, b: str) -> str:
    return (f"## Dokument A\n\n<dokument_a>\n{a}\n</dokument_a>\n\n"
            f"## Dokument B\n\n<dokument_b>\n{b}\n</dokument_b>")


def _text_prvku(prvky: list[PrvekReference]) -> str:
    return "\n".join(f"- **{p.id}** {p.popis}" for p in prvky)


_POPIS_LEPSI = {"A": "lepší A", "B": "lepší B", "stejne": "stejné"}


def _zduvodneni(s1: Srovnani, s2: Srovnani) -> dict[str, list[str]]:
    """Zdůvodnění obou srovnání; u každého je uvedeno, co bylo A a co B."""
    vysledek: dict[str, list[str]] = {}
    for nazev, s in (("Srovnání 1 (A = generovaná, B = reference)", s1),
                     ("Srovnání 2 (A = reference, B = generovaná)", s2)):
        for x in s.kriteria:
            vysledek.setdefault(x.id, []).append(f"{nazev}, {_POPIS_LEPSI[x.lepsi]}: {x.zduvodneni}")
    return vysledek


# ---------------------------------------------------------------- výstupy

def _formular(beh: Beh, nazev_reference: str | None) -> str:
    radky = [
        "# Porovnání s referencí – hodnocení konzultanta",
        "",
        f"Běh: {beh.slozka.name} · finální verze: {beh.stav.finalni_verze}"
        + (f" · reference: {nazev_reference}" if nazev_reference else ""),
        "",
        "Vyplňte po přečtení finálního dokumentu a porovnání s referencí. "
        "Tohle je skutečné měřítko úspěchu; automatické části porovnání slouží k ladění.",
    ]
    for i, otazka in enumerate(OTAZKY_FORMULARE, start=1):
        radky += ["", f"## {i}. {otazka}", "", "Odpověď:"]
    return "\n".join(radky) + "\n"


def _veta_kalibrace(skore: VysledekSkore, cil: float) -> str:
    cil_txt, celkem = format_skore(cil), format_skore(skore.celkem)
    if skore.cil_splnen:
        return f"Reference dosáhla cílového skóre {cil_txt} (skóre {celkem}). Práh je pro tohoto hodnotitele dosažitelný."
    return (
        f"Reference nedosáhla cílového skóre {cil_txt} (skóre {celkem}; {'; '.join(skore.duvody_nesplneni)}). "
        "Když ručně dotažená nabídka práh nesplní, je práh pro tohoto hodnotitele nereálný, "
        "nebo kritéria měří něco jiného, než chceme."
    )


def _html(beh: Beh, zdroje: Zdroje, kriteria: list[Kriterium], v: VysledekPorovnani,
          kalibrace: Hodnoceni, nazev_reference: str | None) -> str:
    finalni = beh.stav.finalni_verze
    klic = f"hodnoceni_{finalni}"
    hodnoceni_gen = beh.data(klic, Hodnoceni) if beh.hotovo(klic) and beh.stav.kroky[klic].data else None
    ref = {s.id: s for s in kalibrace.kriteria}
    gen = {s.id: s for s in hodnoceni_gen.kriteria} if hodnoceni_gen else {}

    def cislo(s: SkoreKriteria | None) -> str:
        return format_skore(s.skore) if s is not None else "–"

    kalibrace_radky = [
        {"id": k.id, "nazev": k.nazev, "reference": cislo(ref.get(k.id)),
         "generovana": cislo(gen.get(k.id)), "zduvodneni": ref[k.id].zduvodneni if k.id in ref else ""}
        for k in kriteria
    ]
    souhrn = [
        {"nazev": nazev, "reference": format_skore(getattr(v.skore_reference, a)),
         "generovana": format_skore(getattr(v.skore_generovane, a))}
        for a, nazev in (("a", "Skupina A – náležitosti"), ("b", "Skupina B – obecná kvalita"),
                         ("c", "Skupina C – bez vymyšlených faktů"), ("celkem", "Celkem"))
    ]
    srovnani = [
        {"id": k.id, "nazev": k.nazev, "verdikt": v.srovnani.get(k.id, "nerozhodne"),
         "zduvodneni": v.zduvodneni.get(k.id, [])}
        for k in kriteria
    ]
    pocty = {d: sum(1 for r in srovnani if r["verdikt"] == d) for d in ("generovana", "reference", "nerozhodne")}
    popisy = {p.id: p.popis for p in v.prvky}
    pokryti = sorted(
        ({"id": p.id, "popis": popisy.get(p.id, ""), "stav": p.stav, "komentar": p.komentar} for p in v.pokryti),
        key=lambda r: _PORADI_POKRYTI[r["stav"]],
    )
    pocty_pokryti = {s: sum(1 for r in pokryti if r["stav"] == s) for s in _PORADI_POKRYTI}

    nazev_finalu = f"FINALNI_{zdroje.konfigurace.profil_nazev}.md"
    env = Environment(loader=FileSystemLoader(_SABLONY), autoescape=True)
    return env.get_template("porovnani.html.j2").render(
        slozka=beh.slozka.name, reference=nazev_reference, finalni=finalni,
        finalni_soubor=nazev_finalu if (beh.slozka / nazev_finalu).exists() else None,
        veta=_veta_kalibrace(v.skore_reference, zdroje.konfigurace.nastaveni.smycka.cilove_skore),
        cil_splnen=v.skore_reference.cil_splnen,
        vymyslena_fakta=len(kalibrace.vymyslena_fakta),
        kalibrace=kalibrace_radky, souhrn=souhrn, srovnani=srovnani, pocty=pocty,
        pokryti=pokryti, pocty_pokryti=pocty_pokryti, formular=FORMULAR,
    )


# ---------------------------------------------------------------- porovnání

def porovnej(
    beh: Beh,
    zdroje: Zdroje,
    reference_md: str,
    hodnotitel: Model,
    hlaseni: Callable[[str], None],
    *,
    nazev_reference: str | None = None,
) -> Path:
    """Pět volání hodnotitele; zapíše porovnani.html, formulář a data/porovnani.json. Vrací cestu k HTML.

    Stav běhu (dokončený) se nemění, přibude jen spotřeba tokenů – i když porovnání selže.
    """
    finalni = beh.stav.finalni_verze
    if beh.stav.stav != "dokoncen" or finalni is None:
        raise InputError(f"Běh {beh.slozka.name} není dokončený; porovnat lze jen dokončený běh.")
    if str(finalni) not in beh.stav.skore or not beh.hotovo(f"navrh_{finalni}"):
        raise InputError(f"Běh {beh.slozka.name} nemá uloženou finální verzi {finalni} nebo její skóre.")

    konf = zdroje.konfigurace
    nalezitosti = beh.data("nalezitosti", VystupNalezitosti).nalezitosti
    kriteria = sestav_kriteria(nalezitosti, konf.kriteria_profilu)
    generovana = beh.text(f"navrh_{finalni}")
    skore_generovane = beh.stav.skore[str(finalni)]

    # Všechny prompty se vykreslí před prvním voláním: chybějící soubor nestojí žádné tokeny.
    promenne = {**spolecne_promenne(zdroje), "typ_dokumentu": konf.profil.typ_dokumentu,
                "kriteria": text_kriterii(kriteria)}
    instrukce = {n: vykresli_prompt(zdroje.prompty, n, **promenne) for n in PROMPTY_POROVNANI}

    def json_s_opravou(schema: type[T], krok: str, instr: str, zadani: str,
                       zkontroluj: Callable[[T], list[str]]) -> T:
        """Validované volání hodnotitele: nejvýš 2 pokusy, druhý s popisem chyb (jako v kroky.py)."""
        return s_opravou(
            hodnotitel, zadani,
            lambda z: hodnotitel.json(instr, z, schema, step=krok),
            zkontroluj,
            lambda x: x.model_dump_json(indent=2),
        )

    try:
        hlaseni("[1/5] Kalibrace: hodnocení reference stejnými kritérii…")
        kalibrace, _ = ohodnot(hodnotitel, zdroje, kriteria, reference_md, [], krok="porovnani_kalibrace")
        skore_reference = spocitej(kalibrace, kriteria, konf.nastaveni)
        hlaseni(f"hotovo, skóre reference {format_skore(skore_reference.celkem)} "
                f"(finální verze {format_skore(skore_generovane.celkem)})")

        def kontrola_srovnani(s: Srovnani) -> list[str]:
            return zkontroluj_srovnani(s, kriteria)

        hlaseni("[2/5] Párové srovnání po kritériích…")
        s1 = json_s_opravou(Srovnani, "porovnani_srovnani_1", instrukce["porovnani_kriteria"],
                            _zadani_srovnani(generovana, reference_md), kontrola_srovnani)
        hlaseni("hotovo")
        hlaseni("[3/5] Párové srovnání s prohozeným pořadím…")
        s2 = json_s_opravou(Srovnani, "porovnani_srovnani_2", instrukce["porovnani_kriteria"],
                            _zadani_srovnani(reference_md, generovana), kontrola_srovnani)
        hlaseni("hotovo")

        hlaseni("[4/5] Obsahové prvky reference…")
        prvky = json_s_opravou(SeznamPrvku, "porovnani_prvky", instrukce["porovnani_prvky"],
                               f"{ZADANI_PRVKY}\n\n{sekce_dokument(reference_md)}", zkontroluj_prvky).prvky
        hlaseni(f"hotovo, počet prvků: {len(prvky)}")

        hlaseni("[5/5] Pokrytí prvků v generované nabídce…")
        pokryti = json_s_opravou(
            Pokryti, "porovnani_pokryti", instrukce["porovnani_pokryti"],
            f"{sekce_dokument(generovana)}\n\n## Prvky k ověření\n\n{_text_prvku(prvky)}",
            lambda p: zkontroluj_pokryti(p, prvky),
        ).polozky
        hlaseni("hotovo")
    finally:
        spotreba = hodnotitel.take_usage()
        if spotreba:
            beh.pridej_spotrebu(spotreba)

    vysledek = VysledekPorovnani(
        skore_reference=skore_reference,
        skore_generovane=skore_generovane,
        srovnani=zkombinuj_srovnani(s1, s2),
        zduvodneni=_zduvodneni(s1, s2),
        prvky=prvky,
        pokryti=pokryti,
    )
    beh.zapis_pevny("data/porovnani.json", vysledek.model_dump_json(indent=2))
    beh.zapis_pevny("data/porovnani_kalibrace.json", kalibrace.model_dump_json(indent=2))
    if not (beh.slozka / FORMULAR).exists():
        beh.zapis_pevny(FORMULAR, _formular(beh, nazev_reference))
    return beh.zapis_pevny(
        "porovnani.html", _html(beh, zdroje, kriteria, vysledek, kalibrace, nazev_reference))

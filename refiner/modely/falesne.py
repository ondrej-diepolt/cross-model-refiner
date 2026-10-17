import re
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel

from refiner.data import Spotreba

T = TypeVar("T", bound=BaseModel)

Odpoved = BaseModel | dict | str | BaseException | Callable[[str, str], BaseModel | dict | str]


class FalesnyModel:
    def __init__(self, odpovedi: dict[str, list[Odpoved]], nazev: str = "falesny"):
        self.nazev = nazev
        self._odpovedi = {k: list(v) for k, v in odpovedi.items()}
        self.volani: list[tuple[str, str, str]] = []
        self._spotreba: list[Spotreba] = []

    def _vezmi(self, krok: str, instrukce: str, zadani: str):
        self.volani.append((krok, instrukce, zadani))
        klic = krok if self._odpovedi.get(krok) else krok.split("_", 1)[0]
        fronta = self._odpovedi.get(klic)
        if not fronta:
            raise AssertionError(f"Falešný model nemá odpověď pro krok {krok!r}")
        odpoved = fronta.pop(0)
        if isinstance(odpoved, BaseException):
            raise odpoved
        self._spotreba.append(Spotreba(krok=krok, model=self.nazev, vstup=1000, vystup=500))
        if callable(odpoved) and not isinstance(odpoved, BaseModel):
            odpoved = odpoved(instrukce, zadani)
        return odpoved

    def json(self, instrukce: str, zadani: str, schema: type[T], *, krok: str,
             effort: str | None = None) -> T:
        odpoved = self._vezmi(krok, instrukce, zadani)
        if isinstance(odpoved, schema):
            return odpoved
        if isinstance(odpoved, BaseModel):
            return schema.model_validate(odpoved.model_dump())
        if isinstance(odpoved, str):
            return schema.model_validate_json(odpoved)
        return schema.model_validate(odpoved)

    def text(self, instrukce: str, zadani: str, *, krok: str) -> str:
        odpoved = self._vezmi(krok, instrukce, zadani)
        if isinstance(odpoved, str):
            return odpoved
        if isinstance(odpoved, BaseModel):
            return odpoved.model_dump_json()
        return str(odpoved)

    def vyzvedni_spotrebu(self) -> list[Spotreba]:
        spotreba, self._spotreba = self._spotreba, []
        return spotreba


# ---------------------------------------------------------------- ukázkový režim (--nanecisto)

DEMO_SKORE = (7.5, 8.5, 9.0, 9.5)   # skóre všech kritérií v hodnocení 1, 2, 3, 4 (a dalších)
_DEMO_ZASOBA = 50                    # odpovědí na krok; s rezervou na opakování a vyšší max_revizi
_DEMO_POZNAMKA = "Ukázka režimu --nanecisto (falešné modely, bez volání API a bez nákladů)."
_DEMO_ROZHODNUTI = ("prijato", "castecne", "odmitnuto")
_DEMO_PRIORITY = ("vysoka", "stredni", "nizka")

_POPTAVKA_RE = re.compile(r"<poptavka>\n?(.*?)\n?</poptavka>", re.S)
_ODRAZKA_RE = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+(.*\S)\s*$")
_NALEZITOST_RE = re.compile(r"^- \*\*(\S+)\*\* (.+?) – citace z poptávky", re.M)
_KRITERIUM_RE = re.compile(r"^- \*\*(\S+)\*\* \((?:A|B) – ", re.M)
_TYP_RE = re.compile(r"dokument(?:u)? typu \*\*(.+?)\*\*")
_NAVRH_RE = re.compile(r"^### (\S+) \(kritérium", re.M)
_PRIJATY_RE = re.compile(r"^### (\S+) \((přijato(?: částečně)?)\)", re.M)
_DOKUMENT_RE = re.compile(r"<dokument>\n(.*)\n</dokument>", re.S)
_ZAPRACOVANO = "## Zapracované připomínky – revize"


def _cislo(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def _unikatni(polozky: list[str]) -> list[str]:
    return list(dict.fromkeys(p for p in polozky if p))


def _demo_citace(instrukce: str) -> list[str]:
    """Až 5 doslovných úryvků poptávky: odrážky, jinak první neprázdné řádky textu."""
    m = _POPTAVKA_RE.search(instrukce)
    radky = (m.group(1) if m else instrukce).splitlines()
    odrazky = [o.group(1).rstrip(" ,;.:") for r in radky if (o := _ODRAZKA_RE.match(r))]
    citace = _unikatni(odrazky)
    if not citace:
        citace = _unikatni([r.strip().rstrip(" ,;.:") for r in radky if not r.lstrip().startswith("#")])
    if not citace:
        citace = _unikatni([r.strip().lstrip("#").strip() for r in radky])
    return citace[:5]


def _demo_nalezitosti(instrukce: str, zadani: str) -> dict:
    nalezitosti = []
    for i, c in enumerate(_demo_citace(instrukce), start=1):
        slova = c.split()
        nazev = " ".join(slova[:8]) + (" …" if len(slova) > 8 else "")
        nalezitosti.append({"id": f"N{i}", "text": nazev[:1].upper() + nazev[1:], "citace": c})
    return {"nalezitosti": nalezitosti}


def _demo_navrh(instrukce: str, zadani: str) -> str:
    typ = (m.group(1) if (m := _TYP_RE.search(instrukce)) else "dokument")
    nalezitosti = _NALEZITOST_RE.findall(instrukce)
    tabulka = "\n".join(f"| {id_} {text} | kap. 3, oddíl {id_} |" for id_, text in nalezitosti)
    oddily = "\n\n".join(
        f"### {id_} – {text}\n\nUkázkový text, který v ostrém běhu napíše model a konkrétně "
        f"v něm splní požadavek poptávky „{text}“."
        for id_, text in nalezitosti
    )
    return (
        f"# {typ[:1].upper()}{typ[1:]} – ukázka bez volání modelů\n\n"
        f"> {_DEMO_POZNAMKA} Dokument ukazuje jen strukturu výstupu.\n\n"
        "## Manažerské shrnutí\n\n"
        "Dodavatel [DOPLNIT: obchodní firma dodavatele – není v podkladech] odpovídá na poptávku "
        "a pokrývá všechny povinné náležitosti uvedené v tabulce níže. Zpracování osobních údajů "
        "bude v souladu s GDPR.\n\n"
        "## Požadavky poptávky\n\n"
        "| Požadavek | Kde v dokumentu |\n|---|---|\n"
        f"{tabulka}\n\n"
        "## Řešení požadavků\n\n"
        f"{oddily}\n\n"
        "## Cena a podmínky\n\n"
        "- Cena: [DOPLNIT: cena – sazba není v podkladech]\n"
        "- Platnost nabídky: [DOPLNIT: doba platnosti nabídky – není v podkladech]\n"
    )


def _demo_hodnoceni(skore: float) -> Callable[[str, str], dict]:
    def odpoved(instrukce: str, zadani: str) -> dict:
        ids = _unikatni(_KRITERIUM_RE.findall(instrukce))
        navrhy = [
            {"id": f"U{j}", "kriterium": ids[(j - 1) % len(ids)] if ids else "N1",
             "misto": f"Kapitola {j + 1}", "problem": "Ukázkový problém, který by našel hodnotitel.",
             "navrh": "Doplnit konkrétní odstavec s popisem řešení.",
             "priorita": _DEMO_PRIORITY[(j - 1) % 3]}
            for j in range(1, 4)
        ]
        return {
            "kriteria": [{"id": i, "skore": skore, "zduvodneni": _DEMO_POZNAMKA, "dukaz": "chybí"}
                         for i in ids],
            "vymyslena_fakta": [],
            "tvrzeni_k_overeni": [{"citace": "v souladu s GDPR",
                                   "proc": "Ukázka položky k ověření – v režimu --nanecisto se nic neověřuje."}],
            "navrhy": navrhy,
            "celkovy_komentar": f"{_DEMO_POZNAMKA} Všechna kritéria mají skóre {_cislo(skore)}.",
        }
    return odpoved


def _demo_posouzeni(instrukce: str, zadani: str) -> dict:
    rozhodnuti = []
    for j, id_ in enumerate(_unikatni(_NAVRH_RE.findall(zadani))):
        r = _DEMO_ROZHODNUTI[j % 3]
        rozhodnuti.append({
            "id_navrhu": id_, "opora": "žádná", "predpoklad": "Ukázkový předpoklad.",
            "dusledek": "Bez vlivu na konzistenci dokumentu.", "rozhodnuti": r,
            "zduvodneni": ("Ukázka odmítnutí: návrh by rozšířil plnění nad rámec poptávky."
                           if r == "odmitnuto" else "Návrh dokument zlepší."),
            "jak_zapracovat": "–" if r == "odmitnuto" else "Doplnit ukázkový odstavec na konec dokumentu.",
        })
    return {"rozhodnuti": rozhodnuti, "shrnuti": _DEMO_POZNAMKA}


def _demo_zapracovani(instrukce: str, zadani: str) -> str:
    m = _DOKUMENT_RE.search(zadani)
    dokument = (m.group(1) if m else "").rstrip()
    revize = dokument.count(_ZAPRACOVANO) + 1
    body = "\n".join(f"- {id_}: ukázkové zapracování ({stav})." for id_, stav in _PRIJATY_RE.findall(zadani))
    return f"{dokument}\n\n{_ZAPRACOVANO} {revize}\n\n{body or '- (žádné)'}\n"


def demo_modely() -> tuple[FalesnyModel, FalesnyModel]:
    """Pisatel a hodnotitel pro --nanecisto: odpovědi fungují pro libovolnou poptávku a projdou
    všemi kontrolami v kroky.py. Skóre roste podle DEMO_SKORE, část návrhů se odmítne."""
    n = _DEMO_ZASOBA
    pisatel = FalesnyModel({
        "nalezitosti": [_demo_nalezitosti] * n,
        "navrh_1": [_demo_navrh] * n,
        "posouzeni": [_demo_posouzeni] * n,
        "navrh": [_demo_zapracovani] * n,
    }, nazev="claude-nanecisto")
    hodnotitel_odpovedi: dict[str, list[Odpoved]] = {
        f"hodnoceni_{k}": [_demo_hodnoceni(s)] * n for k, s in enumerate(DEMO_SKORE, start=1)
    }
    hodnotitel_odpovedi["hodnoceni"] = [_demo_hodnoceni(DEMO_SKORE[-1])] * n
    return pisatel, FalesnyModel(hodnotitel_odpovedi, nazev="gpt-nanecisto")

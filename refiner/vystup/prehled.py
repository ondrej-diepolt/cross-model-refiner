"""Souhrnný přehled běhu jako statické HTML (design kap. 7); vychází jen ze stavu a dat běhu."""
from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from refiner.artifacts import MATERIALS_FILE, OVERVIEW_FILE
from refiner.run import Run
from refiner.data import Evaluation, SuggestionReview, TokenUsage, RequirementsOutput, build_criteria
from refiner.facts import find_placeholders, find_suspicious_facts
from refiner.configuration import Configuration
from refiner.scoring import format_score

_SABLONY = Path(__file__).parent / "sablony"

_DRUHY = {
    "amount": "Částky", "company_id": "IČO", "email": "E-maily", "phone": "Telefony",
    "name": "Jména", "url": "Odkazy",
}
_NAZVY_KROKU = {'request': "Poptávka", 'requirements': "Náležitosti z poptávky"}


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
    m = re.fullmatch(r"(draft|evaluation|review)_(\d+)", klic)
    if not m:
        return klic
    druh, n = m.group(1), m.group(2)
    return {'draft': f"Návrh, verze {n}", 'evaluation': f"Hodnocení {n}", 'review': f"Posouzení {n}"}[druh]


def _doba(beh: Run) -> str:
    konec = beh.state.ended_at
    if konec is None:
        return "neukončeno"
    sekundy = max(0, int((konec - beh.state.created_at).total_seconds()))
    minut, s = divmod(sekundy, 60)
    return f"{minut} min {s} s"


def _nacti_hodnoceni(beh: Run) -> dict[int, Evaluation]:
    vysledek: dict[int, Evaluation] = {}
    for klic, z in beh.state.steps.items():
        m = re.fullmatch(r"evaluation_(\d+)", klic)
        if m and z.data:
            vysledek[int(m.group(1))] = beh.data(klic, Evaluation)
    return dict(sorted(vysledek.items()))


def _nacti_posouzeni(beh: Run) -> dict[int, SuggestionReview]:
    vysledek: dict[int, SuggestionReview] = {}
    for klic, z in beh.state.steps.items():
        m = re.fullmatch(r"review_(\d+)", klic)
        if m and z.data:
            vysledek[int(m.group(1))] = beh.data(klic, SuggestionReview)
    return vysledek


def _bunka(hodnota: float | None, titulek: str = "") -> dict:
    if hodnota is None:
        return {"text": "–", "trida": "", "titulek": titulek}
    return {"text": format_score(hodnota), "trida": _trida_skore(hodnota), "titulek": titulek}


def _tabulka(beh: Run, konf: Configuration, evaluations: dict[int, Evaluation], cisla: list[int]) -> list[dict]:
    """Řádky tabulky skóre; vše se hledá podle čísla hodnocení (ID se v kolech opakují)."""
    if not cisla:
        return []
    kriteria = []
    if beh.is_done('requirements') and beh.state.steps['requirements'].data:
        kriteria = build_criteria(beh.data('requirements', RequirementsOutput).requirements,
                                   konf.profile_criteria)
    skore = beh.state.scores

    def ze_skore(atribut: str) -> list[dict]:
        return [_bunka(getattr(skore[str(c)], atribut) if str(c) in skore else None) for c in cisla]

    radky: list[dict] = []
    for skupina, atribut, nazev in (("A", "a", "Skupina A – průměr náležitostí"),
                                    ("B", "b", "Skupina B – vážený průměr")):
        for k in (x for x in kriteria if x.group == skupina):
            bunky = []
            for c in cisla:
                h = evaluations.get(c)
                s = next((x for x in h.criteria if x.id == k.id), None) if h else None
                bunky.append(_bunka(s.score if s else None, s.rationale if s else ""))
            radky.append({"typ": "kriterium", "id": k.id, "nazev": k.name, "bunky": bunky})
        if kriteria:
            radky.append({"typ": "souhrn", "id": skupina, "nazev": nazev, "bunky": ze_skore(atribut)})
    radky.append({"typ": "souhrn", "id": "C", "nazev": "Skupina C – bez vymyšlených faktů",
                  "bunky": ze_skore("c")})
    radky.append({"typ": "celkem", "id": "", "nazev": "Celkem", "bunky": ze_skore("total")})
    return radky


# Násobky ceny vstupu za tokeny z cache (orientační odhad, v přehledu označený jako odhad).
# Anthropic: zápis do cache (5 min) 1,25×, čtení 0,1×; `input_tokens` cache nezahrnuje.
# OpenAI: čtení z cache 0,5× – PŘEDPOKLAD (sleva se liší podle modelu); `input_tokens`
# tokeny z cache zahrnuje (cached_tokens jsou jejich podmnožina), zápis se neúčtuje.
NASOBEK_ZAPIS_CACHE_ANTHROPIC = 1.25
NASOBEK_CTENI_CACHE_ANTHROPIC = 0.1
NASOBEK_CTENI_CACHE_OPENAI = 0.5


def _je_openai(model: str) -> bool:
    """Poskytovatel podle názvu modelu – stejně jako v kroky.py."""
    return model.lower().startswith("gpt")


def _cena(spotreba: list[TokenUsage], konf: Configuration) -> dict:
    """Souhrn po modelech; `vstup` v řádcích je vždy vstup bez tokenů z cache (u obou služeb)."""
    ceny = konf.settings.prices_usd_per_million
    souhrn: dict[tuple[str, bool], dict] = {}
    for s in spotreba:
        r = souhrn.setdefault((s.model, s.subscription), {
            "model": s.model, "predplatne": s.subscription, "vstup": 0, "vystup": 0,
            "cache_cteni": 0, "cache_zapis": 0})
        # OpenAI počítá tokeny z cache do vstupu; Anthropic ne.
        r["vstup"] += s.input_tokens - s.cache_read_tokens if _je_openai(s.model) else s.input_tokens
        r["vystup"] += s.output_tokens
        r["cache_cteni"] += s.cache_read_tokens
        r["cache_zapis"] += s.cache_write_tokens
    celkem = 0.0
    neznama = False
    radky = []
    for r in souhrn.values():
        c = ceny.get(r["model"])
        if r["predplatne"]:
            cena_txt = "v předplatném"
        elif c is None:
            neznama = True
            cena_txt = "cena neznámá"
        else:
            if _je_openai(r["model"]):
                cache = r["cache_cteni"] * NASOBEK_CTENI_CACHE_OPENAI * c.input
            else:
                cache = (r["cache_cteni"] * NASOBEK_CTENI_CACHE_ANTHROPIC
                         + r["cache_zapis"] * NASOBEK_ZAPIS_CACHE_ANTHROPIC) * c.input
            cena = (r["vstup"] * c.input + cache + r["vystup"] * c.output) / 1_000_000
            celkem += cena
            cena_txt = f"{_desetinne(cena)} USD"
        radky.append({**r, "cena": cena_txt})
    return {
        "radky": radky, "celkem": _desetinne(celkem), "neznama": neznama,
        "predplatne": any(r["predplatne"] for r in radky),
        "jen_predplatne": bool(radky) and all(r["predplatne"] for r in radky),
        **{k: sum(r[k] for r in radky) for k in ("vstup", "vystup", "cache_cteni", "cache_zapis")},
    }


def _kroky(beh: Run) -> list[dict]:
    """Časová osa; odkazy vznikají jen z názvů souborů zapsaných kroků."""
    vysledek = []
    for klic, z in sorted(beh.state.steps.items(), key=lambda kv: kv[1].number):
        odkazy = [{"soubor": z.file, "popis": z.file}]
        if re.fullmatch(r"draft_([2-9]|\d{2,})", klic):
            zmeny = f"{Path(z.file).stem}_zmeny.html"
            if (beh.directory / zmeny).exists():
                odkazy.append({"soubor": zmeny, "popis": "změny proti předchozí verzi"})
        vysledek.append({"cislo": z.number, "popis": _popis_kroku(klic), "odkazy": odkazy})
    return vysledek


def vytvor_prehled(beh: Run, konfigurace: Configuration) -> Path:
    stav = beh.state
    evaluations = _nacti_hodnoceni(beh)
    reviews = _nacti_posouzeni(beh)
    skore = {int(k): v for k, v in stav.scores.items()}
    cisla = sorted(set(evaluations) | set(skore))
    nastaveni = konfigurace.settings

    finalni = stav.final_version if stav.status == 'completed' else None
    fin_skore = skore.get(finalni) if finalni is not None else None
    posledni = cisla[-1] if cisla else None

    duvod = None
    if stav.status == 'completed':
        if stav.stop_reason == 'target_reached':
            cil = format_score(nastaveni.loop.target_score)
            duvod = f"Cíl splněn (skóre {format_score(fin_skore.total) if fin_skore else '?'} ≥ {cil})"
        elif stav.stop_reason == 'revision_limit':
            duvod = f"Vyčerpán limit {nastaveni.loop.max_revisions} revizí"
        elif stav.stop_reason == 'no_changes':
            duvod = "Hodnotitel nenavrhl nic, co by prošlo posouzením"
        else:
            duvod = stav.stop_reason or "Běh skončil"

    vysvetleni = None
    if finalni is not None and fin_skore and posledni is not None and finalni != posledni \
            and posledni in skore:
        # Pořadí výběru (skore.vyber_finalni): splněný cíl, pak nejvyšší skóre, pak pozdější verze.
        if fin_skore.target_met and not skore[posledni].target_met:
            vysvetleni = (
                f"Finální je verze {finalni}, ne poslední verze {posledni}: verze {finalni} splnila cíl, "
                f"verze {posledni} ne ({'; '.join(skore[posledni].unmet_reasons)})."
            )
        else:
            vysvetleni = (
                f"Finální je verze {finalni}, ne poslední verze {posledni}: verze {finalni} má vyšší "
                f"skóre ({format_score(fin_skore.total)}) než verze {posledni} "
                f"({format_score(skore[posledni].total)})."
            )

    placeholdery: list[str] = []
    podezrele: list[dict] = []
    tvrzeni: list = []
    if finalni is not None:
        klic = f"draft_{finalni}"
        if beh.is_done(klic) and (beh.directory / beh.state.steps[klic].file).exists():
            dokument = beh.text(klic)
            placeholdery = find_placeholders(dokument)
            sources = beh.text('request') if beh.is_done('request') else ""
            podklady = beh.directory / "data" / "podklady.md"
            if podklady.exists():
                sources += "\n" + podklady.read_text(encoding="utf-8")
            skupiny: dict[str, list[str]] = {}
            for u in find_suspicious_facts(dokument, sources):
                skupiny.setdefault(u.kind, []).append(u.value)
            podezrele = [{"druh": _DRUHY[d], "hodnoty": v} for d, v in skupiny.items()]
        if finalni in evaluations:
            tvrzeni = evaluations[finalni].claims_to_verify

    # Statistika návrhů po kolech: ID návrhů se opakují v každém kole.
    kola = []
    soucet = {"navrhu": 0, 'accepted': 0, 'partial': 0, 'rejected': 0}
    for c, h in evaluations.items():
        p = reviews.get(c)
        radek = {"kolo": c, "navrhu": len(h.suggestions), 'accepted': 0, 'partial': 0, 'rejected': 0,
                 "posouzeno": p is not None}
        if p:
            for r in p.decisions:
                radek[r.decision] += 1
        for k in soucet:
            soucet[k] += radek[k]
        kola.append(radek)

    nazev_finalu = f"FINALNI_{konfigurace.output_profile_name}"
    soubory = [{"soubor": f"{nazev_finalu}{pripona}",
                "existuje": (beh.directory / f"{nazev_finalu}{pripona}").exists()}
               for pripona in (".docx", ".md")]

    env = Environment(loader=FileSystemLoader(_SABLONY), autoescape=True)
    html = env.get_template("prehled.html.j2").render(
        stav=stav, duvod=duvod, vysvetleni=vysvetleni, finalni=finalni,
        fin_skore=format_score(fin_skore.total) if fin_skore else None,
        soubory=soubory, cisla=cisla, tabulka=_tabulka(beh, konfigurace, evaluations, cisla),
        komentare=[(c, h.overall_comment) for c, h in evaluations.items()],
        placeholdery=placeholdery, tvrzeni=tvrzeni, podezrele=podezrele,
        kroky=_kroky(beh), kola=kola, soucet=soucet, cena=_cena(stav.usage, konfigurace),
        doba=_doba(beh), vytvoreno=f"{stav.created_at:%d. %m. %Y %H:%M}",
        profil=konfigurace.output_profile_name,
    )
    return beh.write_fixed(OVERVIEW_FILE, html)

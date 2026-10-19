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
from pydantic import AliasChoices, BaseModel, Field, field_validator

from refiner.legacy import BETTER_VALUES, COVERAGE_STATUSES, VERDICTS

from refiner.artifacts import COMPARISON_FILE, COMPARISON_FORM
from refiner.run import Run
from refiner.data import (
    Evaluation,
    Criterion,
    CriterionScore,
    ScoreResult,
    RequirementsOutput,
    build_criteria,
)
from refiner.steps import (
    Sources,
    evaluate,
    with_repair,
    document_section,
    common_variables,
    criteria_text,
    render_prompt,
)
from refiner.models.interface import Model
from refiner.scoring import format_score, calculate_score
from refiner.input import SUPPORTED_EXTENSIONS, InputError, read_as_markdown, find_inputs

_SABLONY = Path(__file__).parent / "vystup" / "sablony"

PROMPTY_POROVNANI = ('comparison_criteria', 'comparison_elements', 'comparison_coverage')
OTAZKY_FORMULARE = (
    "Odeslal bych to po doplnění placeholderů?",
    "Kolik minut práce do odeslatelné verze?",
    "Věcné chyby?",
    "Co chybí?",
    "Co je lepší než v referenci?",
)

ZADANI_PRVKY = "Vypiš obsahové prvky dokumentu níže podle pokynů."
_PORADI_POKRYTI = {"chybi": 0, "castecne": 1, "je": 2}

Verdict = Literal['generated', "reference", 'tie']
T = TypeVar("T", bound=BaseModel)


# ---------------------------------------------------------------- schémata (posílají se modelu)

class CriterionComparison(BaseModel):
    id: str
    better: Literal["A", "B", "tie"] = Field(validation_alias=AliasChoices('better', 'lepsi'))
    rationale: str = Field(validation_alias=AliasChoices('rationale', 'zduvodneni'))

    @field_validator("better", mode="before")
    @classmethod
    def _normalize_better(cls, value):
        return BETTER_VALUES.get(value, value) if isinstance(value, str) else value


class PairComparison(BaseModel):
    criteria: list[CriterionComparison] = Field(validation_alias=AliasChoices('criteria', 'kriteria'))


class ReferenceElement(BaseModel):
    id: str
    description: str = Field(validation_alias=AliasChoices('description', 'popis'))


class ReferenceElements(BaseModel):
    elements: list[ReferenceElement] = Field(validation_alias=AliasChoices('elements', 'prvky'))


class ElementCoverage(BaseModel):
    id: str
    status: Literal["present", "partial", "missing"] = Field(validation_alias=AliasChoices('status', 'stav'))
    comment: str = Field(validation_alias=AliasChoices('comment', 'komentar'))

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value):
        return COVERAGE_STATUSES.get(value, value) if isinstance(value, str) else value


class Coverage(BaseModel):
    items: list[ElementCoverage] = Field(validation_alias=AliasChoices('items', 'polozky'))


class ComparisonResult(BaseModel):
    reference_score: ScoreResult = Field(validation_alias=AliasChoices('reference_score', 'skore_reference'))
    generated_score: ScoreResult = Field(validation_alias=AliasChoices('generated_score', 'skore_generovane'))
    comparison: dict[str, Verdict] = Field(validation_alias=AliasChoices('comparison', 'srovnani'))
    rationales: dict[str, list[str]] = Field(validation_alias=AliasChoices('rationales', 'zduvodneni'))
    elements: list[ReferenceElement] = Field(validation_alias=AliasChoices('elements', 'prvky'))
    coverage: list[ElementCoverage] = Field(validation_alias=AliasChoices('coverage', 'pokryti'))

    @field_validator("comparison", mode="before")
    @classmethod
    def _normalize_verdicts(cls, value):
        if not isinstance(value, dict):
            return value
        return {key: VERDICTS.get(verdict, verdict) if isinstance(verdict, str) else verdict
                for key, verdict in value.items()}


# ---------------------------------------------------------------- čisté funkce

_S1: dict[str, Verdict | None] = {"A": 'generated', "B": "reference", 'tie': None}
_S2: dict[str, Verdict | None] = {"A": "reference", "B": 'generated', 'tie': None}


def zkombinuj_srovnani(s1: PairComparison, s2: PairComparison) -> dict[str, Verdict]:
    """V `s1` je A = generovaná, B = reference; v `s2` naopak. Shoda → vítěz, jinak nerozhodně."""
    druhe = {x.id: _S2[x.better] for x in s2.criteria}
    vysledek: dict[str, Verdict] = {}
    for x in s1.criteria:
        prvni = _S1[x.better]
        vysledek[x.id] = prvni if prvni is not None and prvni == druhe.get(x.id) else 'tie'
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


def zkontroluj_srovnani(s: PairComparison, kriteria: list[Criterion]) -> list[str]:
    return _kazde_prave_jednou([x.id for x in s.criteria], [k.id for k in kriteria], "srovnání kritéria")


def zkontroluj_prvky(s: ReferenceElements) -> list[str]:
    if not s.elements:
        return ["Seznam prvků je prázdný."]
    ids = [p.id for p in s.elements]
    return [f"ID prvku {i} je použito vícekrát." for i in sorted({i for i in ids if ids.count(i) > 1})]


def zkontroluj_pokryti(p: Coverage, prvky: list[ReferenceElement]) -> list[str]:
    return _kazde_prave_jednou([x.id for x in p.items], [x.id for x in prvky], "pokrytí prvku")


# ---------------------------------------------------------------- texty pro model

def _zadani_srovnani(a: str, b: str) -> str:
    return (f"## Dokument A\n\n<dokument_a>\n{a}\n</dokument_a>\n\n"
            f"## Dokument B\n\n<dokument_b>\n{b}\n</dokument_b>")


def _text_prvku(prvky: list[ReferenceElement]) -> str:
    return "\n".join(f"- **{p.id}** {p.description}" for p in prvky)


_POPIS_LEPSI = {"A": "lepší A", "B": "lepší B", 'tie': "stejné"}


def _zduvodneni(s1: PairComparison, s2: PairComparison) -> dict[str, list[str]]:
    """Zdůvodnění obou srovnání; u každého je uvedeno, co bylo A a co B."""
    vysledek: dict[str, list[str]] = {}
    for nazev, s in (("Srovnání 1 (A = generovaná, B = reference)", s1),
                     ("Srovnání 2 (A = reference, B = generovaná)", s2)):
        for x in s.criteria:
            vysledek.setdefault(x.id, []).append(f"{nazev}, {_POPIS_LEPSI[x.better]}: {x.rationale}")
    return vysledek


# ---------------------------------------------------------------- výstupy

def _formular(beh: Run, nazev_reference: str | None) -> str:
    radky = [
        "# Porovnání s referencí – hodnocení konzultanta",
        "",
        f"Běh: {beh.directory.name} · finální verze: {beh.state.final_version}"
        + (f" · reference: {nazev_reference}" if nazev_reference else ""),
        "",
        "Vyplňte po přečtení finálního dokumentu a porovnání s referencí. "
        "Tohle je skutečné měřítko úspěchu; automatické části porovnání slouží k ladění.",
    ]
    for i, otazka in enumerate(OTAZKY_FORMULARE, start=1):
        radky += ["", f"## {i}. {otazka}", "", "Odpověď:"]
    return "\n".join(radky) + "\n"


def _veta_kalibrace(skore: ScoreResult, cil: float) -> str:
    cil_txt, celkem = format_score(cil), format_score(skore.total)
    if skore.target_met:
        return f"Reference dosáhla cílového skóre {cil_txt} (skóre {celkem}). Práh je pro tohoto hodnotitele dosažitelný."
    return (
        f"Reference nedosáhla cílového skóre {cil_txt} (skóre {celkem}; {'; '.join(skore.unmet_reasons)}). "
        "Když ručně dotažená nabídka práh nesplní, je práh pro tohoto hodnotitele nereálný, "
        "nebo kritéria měří něco jiného, než chceme."
    )


def _html(beh: Run, sources: Sources, kriteria: list[Criterion], v: ComparisonResult,
          kalibrace: Evaluation, nazev_reference: str | None) -> str:
    finalni = beh.state.final_version
    klic = f"evaluation_{finalni}"
    hodnoceni_gen = beh.data(klic, Evaluation) if beh.is_done(klic) and beh.state.steps[klic].data else None
    ref = {s.id: s for s in kalibrace.criteria}
    gen = {s.id: s for s in hodnoceni_gen.criteria} if hodnoceni_gen else {}

    def cislo(s: CriterionScore | None) -> str:
        return format_score(s.score) if s is not None else "–"

    kalibrace_radky = [
        {"id": k.id, "nazev": k.name, "reference": cislo(ref.get(k.id)),
         'generovana': cislo(gen.get(k.id)), 'zduvodneni': ref[k.id].rationale if k.id in ref else ""}
        for k in kriteria
    ]
    souhrn = [
        {"nazev": nazev, "reference": format_score(getattr(v.reference_score, a)),
         'generovana': format_score(getattr(v.generated_score, a))}
        for a, nazev in (("a", "Skupina A – náležitosti"), ("b", "Skupina B – obecná kvalita"),
                         ("c", "Skupina C – bez vymyšlených faktů"), ("total", "Celkem"))
    ]
    srovnani = [
        {"id": k.id, "nazev": k.name, "verdikt": {'generated': 'generovana', 'reference': 'reference', 'tie': 'nerozhodne'}[v.comparison.get(k.id, 'tie')],
         'zduvodneni': v.rationales.get(k.id, [])}
        for k in kriteria
    ]
    pocty = {d: sum(1 for r in srovnani if r["verdikt"] == d) for d in ('generovana', 'reference', 'nerozhodne')}
    popisy = {p.id: p.description for p in v.elements}
    pokryti = sorted(
        ({"id": p.id, "popis": popisy.get(p.id, ""), "stav": {"present": "je", "partial": "castecne", "missing": "chybi"}[p.status], 'komentar': p.comment} for p in v.coverage),
        key=lambda r: _PORADI_POKRYTI[r["stav"]],
    )
    pocty_pokryti = {s: sum(1 for r in pokryti if r["stav"] == s) for s in _PORADI_POKRYTI}

    nazev_finalu = f"FINALNI_{sources.configuration.output_profile_name}.md"
    env = Environment(loader=FileSystemLoader(_SABLONY), autoescape=True)
    return env.get_template("porovnani.html.j2").render(
        slozka=beh.directory.name, reference=nazev_reference, finalni=finalni,
        finalni_soubor=nazev_finalu if (beh.directory / nazev_finalu).exists() else None,
        veta=_veta_kalibrace(v.reference_score, sources.configuration.settings.loop.target_score),
        cil_splnen=v.reference_score.target_met,
        vymyslena_fakta=len(kalibrace.fabricated_facts),
        kalibrace=kalibrace_radky, souhrn=souhrn, srovnani=srovnani, pocty=pocty,
        pokryti=pokryti, pocty_pokryti=pocty_pokryti, formular=COMPARISON_FORM,
    )


# ---------------------------------------------------------------- porovnání

def porovnej(
    beh: Run,
    sources: Sources,
    reference_md: str,
    hodnotitel: Model,
    hlaseni: Callable[[str], None],
    *,
    nazev_reference: str | None = None,
) -> Path:
    """Pět volání hodnotitele; zapíše porovnani.html, formulář a data/porovnani.json. Vrací cestu k HTML.

    Stav běhu (dokončený) se nemění, přibude jen spotřeba tokenů – i když porovnání selže.
    """
    finalni = beh.state.final_version
    if beh.state.status != 'completed' or finalni is None:
        raise InputError(f"Běh {beh.directory.name} není dokončený; porovnat lze jen dokončený běh.")
    if str(finalni) not in beh.state.scores or not beh.is_done(f"draft_{finalni}"):
        raise InputError(f"Běh {beh.directory.name} nemá uloženou finální verzi {finalni} nebo její skóre.")

    konf = sources.configuration
    nalezitosti = beh.data('requirements', RequirementsOutput).requirements
    kriteria = build_criteria(nalezitosti, konf.profile_criteria)
    generovana = beh.text(f"draft_{finalni}")
    skore_generovane = beh.state.scores[str(finalni)]

    # Všechny prompty se vykreslí před prvním voláním: chybějící soubor nestojí žádné tokeny.
    promenne = {**common_variables(sources), "document_type": konf.profile.document_type,
                'criteria': criteria_text(kriteria)}
    instrukce = {n: render_prompt(sources.prompts, n, **promenne) for n in PROMPTY_POROVNANI}

    def json_s_opravou(schema: type[T], krok: str, instr: str, zadani: str,
                       zkontroluj: Callable[[T], list[str]]) -> T:
        """Validované volání hodnotitele: nejvýš 2 pokusy, druhý s popisem chyb (jako v kroky.py)."""
        return with_repair(
            hodnotitel, zadani,
            lambda z: hodnotitel.json(instr, z, schema, step=krok),
            zkontroluj,
            lambda x: x.model_dump_json(indent=2),
        )

    try:
        hlaseni("[1/5] Kalibrace: hodnocení reference stejnými kritérii…")
        kalibrace, _ = evaluate(hodnotitel, sources, kriteria, reference_md, [], step='comparison_calibration')
        skore_reference = calculate_score(kalibrace, kriteria, konf.settings)
        hlaseni(f"hotovo, skóre reference {format_score(skore_reference.total)} "
                f"(finální verze {format_score(skore_generovane.total)})")

        def kontrola_srovnani(s: PairComparison) -> list[str]:
            return zkontroluj_srovnani(s, kriteria)

        hlaseni("[2/5] Párové srovnání po kritériích…")
        s1 = json_s_opravou(PairComparison, 'comparison_pair_1', instrukce['comparison_criteria'],
                            _zadani_srovnani(generovana, reference_md), kontrola_srovnani)
        hlaseni("hotovo")
        hlaseni("[3/5] Párové srovnání s prohozeným pořadím…")
        s2 = json_s_opravou(PairComparison, 'comparison_pair_2', instrukce['comparison_criteria'],
                            _zadani_srovnani(reference_md, generovana), kontrola_srovnani)
        hlaseni("hotovo")

        hlaseni("[4/5] Obsahové prvky reference…")
        prvky = json_s_opravou(ReferenceElements, 'comparison_elements', instrukce['comparison_elements'],
                               f"{ZADANI_PRVKY}\n\n{document_section(reference_md)}", zkontroluj_prvky).elements
        hlaseni(f"hotovo, počet prvků: {len(prvky)}")

        hlaseni("[5/5] Pokrytí prvků v generované nabídce…")
        pokryti = json_s_opravou(
            Coverage, 'comparison_coverage', instrukce['comparison_coverage'],
            f"{document_section(generovana)}\n\n## Prvky k ověření\n\n{_text_prvku(prvky)}",
            lambda p: zkontroluj_pokryti(p, prvky),
        ).items
        hlaseni("hotovo")
    finally:
        spotreba = hodnotitel.take_usage()
        if spotreba:
            beh.add_usage(spotreba)

    vysledek = ComparisonResult(
        reference_score=skore_reference,
        generated_score=skore_generovane,
        comparison=zkombinuj_srovnani(s1, s2),
        rationales=_zduvodneni(s1, s2),
        elements=prvky,
        coverage=pokryti,
    )
    beh.write_fixed("data/porovnani.json", vysledek.model_dump_json(indent=2))
    beh.write_fixed("data/porovnani_kalibrace.json", kalibrace.model_dump_json(indent=2))
    if not (beh.directory / COMPARISON_FORM).exists():
        beh.write_fixed(COMPARISON_FORM, _formular(beh, nazev_reference))
    return beh.write_fixed(
        COMPARISON_FILE, _html(beh, sources, kriteria, vysledek, kalibrace, nazev_reference))

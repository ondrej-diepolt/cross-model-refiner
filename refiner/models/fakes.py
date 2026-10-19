import re
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel

from refiner.data import TokenUsage

T = TypeVar("T", bound=BaseModel)

Response = BaseModel | dict | str | BaseException | Callable[[str, str], BaseModel | dict | str]


class FakeModel:
    def __init__(self, responses: dict[str, list[Response]], name: str = "fake"):
        self.name = name
        self._responses = {k: list(v) for k, v in responses.items()}
        self.calls: list[tuple[str, str, str]] = []
        self._usage: list[TokenUsage] = []

    def _take(self, step: str, instructions: str, task: str):
        self.calls.append((step, instructions, task))
        key = step if self._responses.get(step) else step.split("_", 1)[0]
        queue = self._responses.get(key)
        if not queue:
            raise AssertionError(f"Fake model has no response for step {step!r}")
        response = queue.pop(0)
        if isinstance(response, BaseException):
            raise response
        self._usage.append(TokenUsage(step=step, model=self.name, input_tokens=1000, output_tokens=500))
        if callable(response) and not isinstance(response, BaseModel):
            response = response(instructions, task)
        return response

    def json(self, instructions: str, task: str, schema: type[T], *, step: str,
             effort: str | None = None) -> T:
        response = self._take(step, instructions, task)
        if isinstance(response, schema):
            return response
        if isinstance(response, BaseModel):
            return schema.model_validate(response.model_dump())
        if isinstance(response, str):
            return schema.model_validate_json(response)
        return schema.model_validate(response)

    def text(self, instructions: str, task: str, *, step: str) -> str:
        response = self._take(step, instructions, task)
        if isinstance(response, str):
            return response
        if isinstance(response, BaseModel):
            return response.model_dump_json()
        return str(response)

    def take_usage(self) -> list[TokenUsage]:
        usage, self._usage = self._usage, []
        return usage


# ---------------------------------------------------------------- demo mode (--nanecisto)

DEMO_SCORES = (7.5, 8.5, 9.0, 9.5)   # all criterion scores in evaluations 1, 2, 3, 4 (and later)
_DEMO_STOCK = 50                    # responses per step, with room for retries and higher revision limits
_DEMO_NOTE = "Ukázka režimu --nanecisto (falešné modely, bez volání API a bez nákladů)."
_DEMO_DECISIONS = ('accepted', 'partial', 'rejected')
_DEMO_PRIORITY = ('high', 'medium', 'low')

_REQUEST_RE = re.compile(r"<poptavka>\n?(.*?)\n?</poptavka>", re.S)
_BULLET_RE = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+(.*\S)\s*$")
_REQUIREMENT_RE = re.compile(r"^- \*\*(\S+)\*\* (.+?) – citace z poptávky", re.M)
_CRITERION_RE = re.compile(r"^- \*\*(\S+)\*\* \((?:A|B) – ", re.M)
_TYPE_RE = re.compile(r"dokument(?:u)? typu \*\*(.+?)\*\*")
_SUGGESTION_RE = re.compile(r"^### (\S+) \(kritérium", re.M)
_ACCEPTED_RE = re.compile(r"^### (\S+) \((přijato(?: částečně)?)\)", re.M)
_DOCUMENT_RE = re.compile(r"<dokument>\n(.*)\n</dokument>", re.S)
_INCORPORATED = "## Zapracované připomínky – revize"


def _number(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(p for p in items if p))


def _demo_citations(instructions: str) -> list[str]:
    """Up to five verbatim request excerpts: bullets, otherwise the first nonempty lines."""
    m = _REQUEST_RE.search(instructions)
    lines = (m.group(1) if m else instructions).splitlines()
    bullets = [o.group(1).rstrip(" ,;.:") for r in lines if (o := _BULLET_RE.match(r))]
    citations = _unique(bullets)
    if not citations:
        citations = _unique([r.strip().rstrip(" ,;.:") for r in lines if not r.lstrip().startswith("#")])
    if not citations:
        citations = _unique([r.strip().lstrip("#").strip() for r in lines])
    return citations[:5]


def _demo_requirements(instructions: str, task: str) -> dict:
    requirements = []
    for i, c in enumerate(_demo_citations(instructions), start=1):
        words = c.split()
        name = " ".join(words[:8]) + (" …" if len(words) > 8 else "")
        requirements.append({"id": f"N{i}", "text": name[:1].upper() + name[1:], 'citation': c})
    return {'requirements': requirements}


def _demo_draft(instructions: str, task: str) -> str:
    type_ = (m.group(1) if (m := _TYPE_RE.search(instructions)) else "dokument")
    requirements = _REQUIREMENT_RE.findall(instructions)
    table = "\n".join(f"| {id_} {text} | kap. 3, oddíl {id_} |" for id_, text in requirements)
    sections = "\n\n".join(
        f"### {id_} – {text}\n\nUkázkový text, který v ostrém běhu napíše model a konkrétně "
        f"v něm splní požadavek poptávky „{text}“."
        for id_, text in requirements
    )
    return (
        f"# {type_[:1].upper()}{type_[1:]} – ukázka bez volání modelů\n\n"
        f"> {_DEMO_NOTE} Dokument ukazuje jen strukturu výstupu.\n\n"
        "## Manažerské shrnutí\n\n"
        "Dodavatel [DOPLNIT: obchodní firma dodavatele – není v podkladech] odpovídá na poptávku "
        "a pokrývá všechny povinné náležitosti uvedené v tabulce níže. Zpracování osobních údajů "
        "bude v souladu s GDPR.\n\n"
        "## Požadavky poptávky\n\n"
        "| Požadavek | Kde v dokumentu |\n|---|---|\n"
        f"{table}\n\n"
        "## Řešení požadavků\n\n"
        f"{sections}\n\n"
        "## Cena a podmínky\n\n"
        "- Cena: [DOPLNIT: cena – sazba není v podkladech]\n"
        "- Platnost nabídky: [DOPLNIT: doba platnosti nabídky – není v podkladech]\n"
    )


def _demo_evaluation(score: float) -> Callable[[str, str], dict]:
    def response(instructions: str, task: str) -> dict:
        ids = _unique(_CRITERION_RE.findall(instructions))
        suggestions = [
            {"id": f"U{j}", 'criterion': ids[(j - 1) % len(ids)] if ids else "N1",
             'location': f"Kapitola {j + 1}", "problem": "Ukázkový problém, který by našel hodnotitel.",
             'suggestion': "Doplnit konkrétní odstavec s popisem řešení.",
             'priority': _DEMO_PRIORITY[(j - 1) % 3]}
            for j in range(1, 4)
        ]
        return {
            'criteria': [{"id": i, 'score': score, 'rationale': _DEMO_NOTE, 'evidence': "chybí"}
                         for i in ids],
            'fabricated_facts': [],
            'claims_to_verify': [{'citation': "v souladu s GDPR",
                                   'reason': "Ukázka položky k ověření – v režimu --nanecisto se nic neověřuje."}],
            'suggestions': suggestions,
            'overall_comment': f"{_DEMO_NOTE} Všechna kritéria mají skóre {_number(score)}.",
        }
    return response


def _demo_review(instructions: str, task: str) -> dict:
    decisions = []
    for j, id_ in enumerate(_unique(_SUGGESTION_RE.findall(task))):
        r = _DEMO_DECISIONS[j % 3]
        decisions.append({
            'suggestion_id': id_, 'support': "žádná", 'assumption': "Ukázkový předpoklad.",
            'consequence': "Bez vlivu na konzistenci dokumentu.", 'decision': r,
            'rationale': ("Ukázka odmítnutí: návrh by rozšířil plnění nad rámec poptávky."
                           if r == 'rejected' else "Návrh dokument zlepší."),
            'implementation': "–" if r == 'rejected' else "Doplnit ukázkový odstavec na konec dokumentu.",
        })
    return {'decisions': decisions, 'summary': _DEMO_NOTE}


def _demo_revision(instructions: str, task: str) -> str:
    m = _DOCUMENT_RE.search(task)
    document = (m.group(1) if m else "").rstrip()
    revision = document.count(_INCORPORATED) + 1
    body = "\n".join(f"- {id_}: ukázkové zapracování ({status})." for id_, status in _ACCEPTED_RE.findall(task))
    return f"{document}\n\n{_INCORPORATED} {revision}\n\n{body or '- (žádné)'}\n"


def demo_models() -> tuple[FakeModel, FakeModel]:
    """Demo writer and evaluator: responses support arbitrary requests and pass all step
    validations. Scores follow DEMO_SCORES; some suggestions are rejected."""
    n = _DEMO_STOCK
    writer = FakeModel({
        'requirements': [_demo_requirements] * n,
        'draft_1': [_demo_draft] * n,
        'review': [_demo_review] * n,
        'draft': [_demo_revision] * n,
    }, name="claude-nanecisto")
    evaluator_responses: dict[str, list[Response]] = {
        f"evaluation_{k}": [_demo_evaluation(s)] * n for k, s in enumerate(DEMO_SCORES, start=1)
    }
    evaluator_responses['evaluation'] = [_demo_evaluation(DEMO_SCORES[-1])] * n
    return writer, FakeModel(evaluator_responses, name="gpt-nanecisto")

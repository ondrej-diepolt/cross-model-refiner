"""Static Czech run overview derived only from recorded state and step data."""
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

TEMPLATES = Path(__file__).parent / "templates"

FACT_LABELS = {
    "amount": "Částky", "company_id": "IČO", "email": "E-maily", "phone": "Telefony",
    "name": "Jména", "url": "Odkazy",
}
STEP_LABELS = {'request': "Poptávka", 'requirements': "Náležitosti z poptávky"}


def _score_class(x: float) -> str:
    if x < 7:
        return 'score-red'
    if x < 9:
        return 'score-orange'
    return 'score-green'


def _decimal(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def _step_description(key: str) -> str:
    if key in STEP_LABELS:
        return STEP_LABELS[key]
    m = re.fullmatch(r"(draft|evaluation|review)_(\d+)", key)
    if not m:
        return key
    kind, n = m.group(1), m.group(2)
    return {'draft': f"Návrh, verze {n}", 'evaluation': f"Hodnocení {n}", 'review': f"Posouzení {n}"}[kind]


def _duration(run: Run) -> str:
    end = run.state.ended_at
    if end is None:
        return "neukončeno"
    seconds = max(0, int((end - run.state.created_at).total_seconds()))
    minutes, s = divmod(seconds, 60)
    return f"{minutes} min {s} s"


def _load_evaluations(run: Run) -> dict[int, Evaluation]:
    result: dict[int, Evaluation] = {}
    for key, z in run.state.steps.items():
        m = re.fullmatch(r"evaluation_(\d+)", key)
        if m and z.data:
            result[int(m.group(1))] = run.data(key, Evaluation)
    return dict(sorted(result.items()))


def _load_reviews(run: Run) -> dict[int, SuggestionReview]:
    result: dict[int, SuggestionReview] = {}
    for key, z in run.state.steps.items():
        m = re.fullmatch(r"review_(\d+)", key)
        if m and z.data:
            result[int(m.group(1))] = run.data(key, SuggestionReview)
    return result


def _cell(value: float | None, title: str = "") -> dict:
    if value is None:
        return {"text": "–", 'css_class': "", 'title': title}
    return {"text": format_score(value), 'css_class': _score_class(value), 'title': title}


def _score_table(run: Run, configuration: Configuration, evaluations: dict[int, Evaluation], numbers: list[int]) -> list[dict]:
    """Score table rows indexed by evaluation number; criterion IDs recur in later rounds."""
    if not numbers:
        return []
    criteria = []
    if run.is_done('requirements') and run.state.steps['requirements'].data:
        criteria = build_criteria(run.data('requirements', RequirementsOutput).requirements,
                                   configuration.profile_criteria)
    scores = run.state.scores

    def from_scores(attribute: str) -> list[dict]:
        return [_cell(getattr(scores[str(c)], attribute) if str(c) in scores else None) for c in numbers]

    rows: list[dict] = []
    for group, attribute, name in (("A", "a", "Skupina A – průměr náležitostí"),
                                    ("B", "b", "Skupina B – vážený průměr")):
        for k in (x for x in criteria if x.group == group):
            cells = []
            for c in numbers:
                h = evaluations.get(c)
                s = next((x for x in h.criteria if x.id == k.id), None) if h else None
                cells.append(_cell(s.score if s else None, s.rationale if s else ""))
            rows.append({'type': 'criterion', "id": k.id, 'name': k.name, 'cells': cells})
        if criteria:
            rows.append({'type': 'summary', "id": group, 'name': name, 'cells': from_scores(attribute)})
    rows.append({'type': 'summary', "id": "C", 'name': "Skupina C – bez vymyšlených faktů",
                  'cells': from_scores("c")})
    rows.append({'type': 'total', "id": "", 'name': "Celkem", 'cells': from_scores("total")})
    return rows


# Cache prices as input-price multipliers, shown as estimates in the overview.
# Anthropic: five-minute cache write x1.25, read x0.1; input_tokens excludes cache.
# OpenAI: assumed cache read x0.5 (actual discount varies by model); input_tokens
# includes cached_tokens as a subset; there is no cache write charge.
ANTHROPIC_CACHE_WRITE_MULTIPLIER = 1.25
ANTHROPIC_CACHE_READ_MULTIPLIER = 0.1
OPENAI_CACHE_READ_MULTIPLIER = 0.5


def _is_openai(model: str) -> bool:
    """Infer provider from the model name, matching steps.py."""
    return model.lower().startswith("gpt")


def _cost(usage: list[TokenUsage], configuration: Configuration) -> dict:
    """Aggregate model usage; input_tokens always excludes cached tokens for both providers."""
    prices = configuration.settings.prices_usd_per_million
    summary: dict[tuple[str, bool], dict] = {}
    for s in usage:
        r = summary.setdefault((s.model, s.subscription), {
            "model": s.model, 'subscription': s.subscription, 'input_tokens': 0, "output_tokens": 0,
            'cache_read_tokens': 0, 'cache_write_tokens': 0})
        # OpenAI includes cached tokens in input; Anthropic does not.
        r['input_tokens'] += s.input_tokens - s.cache_read_tokens if _is_openai(s.model) else s.input_tokens
        r["output_tokens"] += s.output_tokens
        r['cache_read_tokens'] += s.cache_read_tokens
        r['cache_write_tokens'] += s.cache_write_tokens
    total = 0.0
    unknown = False
    rows = []
    for r in summary.values():
        c = prices.get(r["model"])
        if r['subscription']:
            cost_text = "v předplatném"
        elif c is None:
            unknown = True
            cost_text = "cena neznámá"
        else:
            if _is_openai(r["model"]):
                cache = r['cache_read_tokens'] * OPENAI_CACHE_READ_MULTIPLIER * c.input
            else:
                cache = (r['cache_read_tokens'] * ANTHROPIC_CACHE_READ_MULTIPLIER
                         + r['cache_write_tokens'] * ANTHROPIC_CACHE_WRITE_MULTIPLIER) * c.input
            cost = (r['input_tokens'] * c.input + cache + r["output_tokens"] * c.output) / 1_000_000
            total += cost
            cost_text = f"{_decimal(cost)} USD"
        rows.append({**r, 'cost': cost_text})
    return {
        'rows': rows, 'total': _decimal(total), 'unknown': unknown,
        'subscription': any(r['subscription'] for r in rows),
        'subscription_only': bool(rows) and all(r['subscription'] for r in rows),
        **{k: sum(r[k] for r in rows) for k in ('input_tokens', "output_tokens", 'cache_read_tokens', 'cache_write_tokens')},
    }


def _steps(run: Run) -> list[dict]:
    """Timeline links use the filenames stored in step records."""
    result = []
    for key, z in sorted(run.state.steps.items(), key=lambda kv: kv[1].number):
        links = [{'file': z.file, 'description': z.file}]
        if re.fullmatch(r"draft_([2-9]|\d{2,})", key):
            changes = f"{Path(z.file).stem}_zmeny.html"
            if (run.directory / changes).exists():
                links.append({'file': changes, 'description': "změny proti předchozí verzi"})
        result.append({'number': z.number, 'description': _step_description(key), 'links': links})
    return result


def create_overview(run: Run, configuration: Configuration) -> Path:
    state = run.state
    evaluations = _load_evaluations(run)
    reviews = _load_reviews(run)
    scores = {int(k): v for k, v in state.scores.items()}
    numbers = sorted(set(evaluations) | set(scores))
    settings = configuration.settings

    final_version = state.final_version if state.status == 'completed' else None
    final_score = scores.get(final_version) if final_version is not None else None
    latest = numbers[-1] if numbers else None

    reason = None
    if state.status == 'completed':
        if state.stop_reason == 'target_reached':
            target = format_score(settings.loop.target_score)
            reason = f"Cíl splněn (skóre {format_score(final_score.total) if final_score else '?'} ≥ {target})"
        elif state.stop_reason == 'revision_limit':
            reason = f"Vyčerpán limit {settings.loop.max_revisions} revizí"
        elif state.stop_reason == 'no_changes':
            reason = "Hodnotitel nenavrhl nic, co by prošlo posouzením"
        else:
            reason = state.stop_reason or "Běh skončil"

    explanation = None
    if final_version is not None and final_score and latest is not None and final_version != latest\
            and latest in scores:
        # Selection order: met target, highest score, then later version.
        if final_score.target_met and not scores[latest].target_met:
            explanation = (
                f"Finální je verze {final_version}, ne poslední verze {latest}: verze {final_version} splnila cíl, "
                f"verze {latest} ne ({'; '.join(scores[latest].unmet_reasons)})."
            )
        else:
            explanation = (
                f"Finální je verze {final_version}, ne poslední verze {latest}: verze {final_version} má vyšší "
                f"skóre ({format_score(final_score.total)}) než verze {latest} "
                f"({format_score(scores[latest].total)})."
            )

    placeholders: list[str] = []
    suspicious: list[dict] = []
    claims: list = []
    if final_version is not None:
        key = f"draft_{final_version}"
        if run.is_done(key) and (run.directory / run.state.steps[key].file).exists():
            document = run.text(key)
            placeholders = find_placeholders(document)
            sources = run.text('request') if run.is_done('request') else ""
            materials = run.directory / "data" / "podklady.md"
            if materials.exists():
                sources += "\n" + materials.read_text(encoding="utf-8")
            groups: dict[str, list[str]] = {}
            for u in find_suspicious_facts(document, sources):
                groups.setdefault(u.kind, []).append(u.value)
            suspicious = [{'kind': FACT_LABELS[d], 'values': v} for d, v in groups.items()]
        if final_version in evaluations:
            claims = evaluations[final_version].claims_to_verify

    # Suggestion IDs recur, so aggregate each round separately.
    rounds = []
    totals = {'suggestions': 0, 'accepted': 0, 'partial': 0, 'rejected': 0}
    for c, h in evaluations.items():
        p = reviews.get(c)
        row = {'round': c, 'suggestions': len(h.suggestions), 'accepted': 0, 'partial': 0, 'rejected': 0,
                 'reviewed': p is not None}
        if p:
            for r in p.decisions:
                row[r.decision] += 1
        for k in totals:
            totals[k] += row[k]
        rounds.append(row)

    final_name = f"FINALNI_{configuration.output_profile_name}"
    files = [{'file': f"{final_name}{suffix}",
                'exists': (run.directory / f"{final_name}{suffix}").exists()}
               for suffix in (".docx", ".md")]

    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True)
    html = env.get_template("overview.html.j2").render(
        state=state, reason=reason, explanation=explanation, final_version=final_version,
        final_score=format_score(final_score.total) if final_score else None,
        files=files, numbers=numbers, table=_score_table(run, configuration, evaluations, numbers),
        comments=[(c, h.overall_comment) for c, h in evaluations.items()],
        placeholders=placeholders, claims=claims, suspicious=suspicious,
        steps=_steps(run), rounds=rounds, totals=totals, cost=_cost(state.usage, configuration),
        duration=_duration(run), created_at=f"{state.created_at:%d. %m. %Y %H:%M}",
        profile_name=configuration.output_profile_name,
    )
    return run.write_fixed(OVERVIEW_FILE, html)

from datetime import datetime

from refiner.data import Evaluation, TokenUsage, ScoreResult
from refiner.models.fakes import FakeModel
from refiner.loop import run_loop
from refiner.output.overview import create_overview
from tests.helpers import make_run, make_evaluation, make_criteria, scripted_responses, scripted_models


def test_legacy_overview_and_markdown_keep_czech_labels(legacy_completed):
    from refiner.aplikace import otevri_dokonceny
    from refiner.data import RequirementsOutput, build_criteria
    from refiner.output.markdown import evaluation_markdown, review_markdown
    from tests.helpers import make_review

    run, sources = otevri_dokonceny(legacy_completed)
    evaluation = run.data("evaluation_1", Evaluation)
    review = make_review(evaluation)
    criteria = build_criteria(run.data("requirements", RequirementsOutput).requirements,
                              sources.configuration.profile_criteria)
    evaluation.suggestions[0].priority = "high"
    evaluation.suggestions[1].priority = "low"
    md = evaluation_markdown(1, evaluation, run.state.scores["1"], criteria)
    assert "vysoka" in md and "nizka" in md and "high" not in md and "low" not in md
    review.decisions[0].decision = "partial"
    review.decisions[1].decision = "rejected"
    md = review_markdown(1, evaluation, review)
    assert "částečně" in md and "odmítnuto" in md and "partial" not in md and "rejected" not in md
    path = create_overview(run, sources.configuration)
    html = path.read_text(encoding="utf-8")
    assert path.name == "prehled.html" and 'href="FINALNI_nabidka.md"' in html
    assert "Cíl splněn" in html and "completed" not in html and "accepted" not in html
    assert not (run.directory / "overview.html").exists()


def test_overview_links_preserve_policy_and_custom_tokens(legacy_completed):
    from dataclasses import replace
    from refiner.aplikace import otevri_dokonceny

    run, sources = otevri_dokonceny(legacy_completed)
    for profile_id, token in (("policy", "smernice"), ("custom_offer", "custom_offer")):
        run.write_fixed(f"FINALNI_{token}.md", "# Dokument\n")
        configuration = replace(sources.configuration, profile_id=profile_id, output_profile_name=token)
        html = create_overview(run, configuration).read_text(encoding="utf-8")
        assert f'href="FINALNI_{token}.md"' in html
        assert "FINAL_policy" not in html and "FINAL_custom_offer" not in html


def test_overview_shows_output_token_counts_for_models_and_total(legacy_completed):
    import html as html_module
    import re
    from refiner.aplikace import otevri_dokonceny

    run, sources = otevri_dokonceny(legacy_completed)
    html = create_overview(run, sources.configuration).read_text(encoding="utf-8")
    rows = [[" ".join(html_module.unescape(re.sub(r"<[^>]+>", "", cell)).split())
             for cell in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row, flags=re.S)]
            for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", html, flags=re.S)]
    assert ["claude-falesny", "2000", "0 / 0", "1000", "cena neznámá"] in rows
    assert ["gpt-falesny", "1000", "0 / 0", "500", "cena neznámá"] in rows
    assert ["Celkem", "3000", "0 / 0", "1500", "0,00 USD + cena neznámá u některých modelů"] in rows


def _silent(_: str) -> None:
    pass


def _html(run, sources) -> str:
    return create_overview(run, sources.configuration).read_text(encoding="utf-8")


def test_overview_completed_run(tmp_path, sources):
    run = make_run(tmp_path, sources)
    v = run_loop(run, sources, *scripted_models([7.0, 9.5]), report=_silent)
    assert v.reason == 'target_reached'
    run.write_fixed("FINALNI_nabidka.md", "# Nabídka\n\nSazba: [DOPLNIT: sazba za MD]\n")
    run.finish('completed', v.reason, final_version=v.final_version)
    path = create_overview(run, sources.configuration)
    assert path == run.directory / "prehled.html"
    html = path.read_text(encoding="utf-8")
    assert "Cíl splněn" in html and "FINALNI_nabidka.docx" in html
    assert "Hodnocení 1" in html and "Hodnocení 2" in html and "9,6" in html


def test_overview_placeholders_from_final_version(tmp_path, sources):
    run = make_run(tmp_path, sources)
    run_loop(run, sources, *scripted_models([9.5]), report=_silent)
    run.write_fixed("03_navrh_v1.md", "# Nabídka\n\nSazba: [DOPLNIT: sazba za MD]\n")
    run.finish('completed', 'target_reached', final_version=1)
    assert "sazba za MD" in _html(run, sources)


def test_overview_links_recorded_step_files(tmp_path, sources):
    run = make_run(tmp_path, sources)
    v = run_loop(run, sources, *scripted_models([7.0, 9.5]), report=_silent)
    run.finish('completed', v.reason, final_version=v.final_version)
    html = _html(run, sources)
    for z in run.state.steps.values():
        assert f'href="{z.file}"' in html
    assert 'href="04_hodnoceni_1.md"' in html
    assert "_zmeny.html" in html


def test_overview_interrupted_before_evaluation(tmp_path, sources):
    run = make_run(tmp_path, sources)
    writer, evaluator = scripted_responses([9.5])
    writer['requirements'] = [RuntimeError("Spojení vypadlo")]
    try:
        run_loop(run, sources, FakeModel(writer, name="c"), FakeModel(evaluator, name="g"),
                     report=_silent)
    except Exception:
        pass
    run.finish('interrupted', error="Spojení vypadlo")
    html = _html(run, sources)
    assert "Běh byl přerušen" in html and "Spojení vypadlo" in html and "pokracovat.bat" in html


def test_overview_running_without_end_time(tmp_path, sources):
    run = make_run(tmp_path, sources)
    assert "prehled" in create_overview(run, sources.configuration).name


def test_overview_escapes_model_html(tmp_path, sources):
    run = make_run(tmp_path, sources)
    run_loop(run, sources, *scripted_models([9.5]), report=_silent)
    h = run.data('evaluation_1', Evaluation)
    h.criteria[0].rationale = "<script>alert(1)</script>"
    h.suggestions[0].problem = "<script>alert(2)</script>"
    h.claims_to_verify = []
    run.write_fixed("data/04_hodnoceni_1.json", h.model_dump_json())
    run.write_fixed("03_navrh_v1.md", "# N\n\n<script>alert(3)</script> [DOPLNIT: <b>x</b>]\n")
    run.finish('completed', 'target_reached', final_version=1)
    html = _html(run, sources)
    assert "<script" not in html and "<b>x</b>" not in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html


def test_overview_escapes_claims_to_verify(tmp_path, sources):
    from refiner.data import ClaimToVerify

    run = make_run(tmp_path, sources)
    run_loop(run, sources, *scripted_models([9.5]), report=_silent)
    h = run.data('evaluation_1', Evaluation)
    h.claims_to_verify = [ClaimToVerify(citation="<script>alert(1)</script>", reason="Zákon č. 134/2016")]
    run.write_fixed("data/04_hodnoceni_1.json", h.model_dump_json())
    run.finish('completed', 'target_reached', final_version=1)
    html = _html(run, sources)
    assert "<script" not in html and "&lt;script&gt;alert(1)" in html and "134/2016" in html


def test_overview_cost_and_tokens(tmp_path, sources):
    run = make_run(tmp_path, sources)
    run.add_usage([TokenUsage(step="a", model="claude-opus-5-5", input_tokens=1_000_000, output_tokens=0),
                         TokenUsage(step="b", model="claude-opus-5-5", input_tokens=1_000_000, output_tokens=0),
                         TokenUsage(step="c", model="neznamy-model", input_tokens=10, output_tokens=5)])
    html = _html(run, sources)
    assert "8,00" in html and "orientačně" in html and "cena neznámá" in html


def test_cache_cost_by_provider(sources):
    """Anthropic excludes cache from input (write x1.25, read x0.1); OpenAI includes cache (read x0.5)."""
    from refiner.output.overview import _cost

    cost = _cost([
        # 4 + 2 000 000×0,1×4 + 400 000×1,25×4 + 100 000×20 (per million) = 4 + 0,8 + 2 + 2 = 8,80
        TokenUsage(step="a", model="claude-opus-5-5", input_tokens=1_000_000, output_tokens=100_000,
                 cache_read_tokens=2_000_000, cache_write_tokens=400_000),
        # (1 000 000 − 600 000)×10 + 600 000×0,5×10 + 10 000×50 (per million) = 4 + 3 + 0,5 = 7,50
        TokenUsage(step="b", model="gpt-6-astra", input_tokens=1_000_000, output_tokens=10_000, cache_read_tokens=600_000),
    ], sources.configuration)
    assert [r['cost'] for r in cost['rows']] == ["8,80 USD", "7,50 USD"]
    assert cost['total'] == "16,30"


def test_overview_cost_labels_cache_estimate(tmp_path, sources):
    run = make_run(tmp_path, sources)
    run.add_usage([TokenUsage(step="a", model="claude-opus-5-5", input_tokens=10, output_tokens=5)])
    html = _html(run, sources)
    assert "Cena (orientačně, cache odhadem)" in html and "bez slev za cache" not in html


def test_overview_explains_met_target_selection(tmp_path, sources):
    run = make_run(tmp_path, sources)
    run.save_score(1, ScoreResult(a=9.5, b=9.5, c=10, total=9.5, target_met=True, unmet_reasons=[]))
    run.save_score(2, ScoreResult(a=9.8, b=9.8, c=7, total=9.6, target_met=False,
                                    unmet_reasons=["text obsahuje vymyšlené fakty (1)"]))
    run.finish('completed', 'target_reached', final_version=1)
    html = _html(run, sources)
    assert "verze 1 splnila cíl" in html and "vyšší skóre" not in html


def test_overview_explains_earlier_final_version(tmp_path, sources):
    run = make_run(tmp_path, sources)
    for k, c in enumerate([6.0, 8.0, 7.0, 7.5], start=1):
        run.save_score(k, ScoreResult(a=c, b=c, c=10, total=c, target_met=False, unmet_reasons=[]))
    run.finish('completed', 'revision_limit', final_version=2)
    html = _html(run, sources)
    assert "vyšší skóre" in html and "verze 2" in html and "Vyčerpán limit" in html


def test_overview_criteria_table_and_score_colors(tmp_path, sources):
    run = make_run(tmp_path, sources)
    v = run_loop(run, sources, *scripted_models([6.0, 9.5]), report=_silent)
    run.finish('completed', v.reason, final_version=v.final_version)
    html = _html(run, sources)
    assert "Celkem" in html and "N1" in html and "B1" in html
    assert 'score-red' in html and 'score-green' in html


def test_overview_suggestion_stats_and_later_rounds(tmp_path, sources):
    run = make_run(tmp_path, sources)
    run_loop(run, sources, *scripted_models([7.0] * 4, decision='partial'), report=_silent)
    run.finish('completed', 'revision_limit', final_version=2)
    assert "Částečně" in _html(run, sources)


def test_subscription_usage_has_no_token_cost(sources):
    from refiner.output.overview import _cost, _decimal

    cost = _cost([TokenUsage(step='suggestion', model="claude-opus-5-5", input_tokens=1000, output_tokens=500, subscription=True),
                  TokenUsage(step='evaluation_1', model="gpt-6-astra", input_tokens=1000, output_tokens=500, subscription=True)],
                 sources.configuration)
    assert [r['cost'] for r in cost['rows']] == ["v předplatném", "v předplatném"]
    assert cost['subscription_only'] and cost['subscription'] and not cost['unknown']
    assert cost['total'] == _decimal(0.0)


def test_mixed_billing_separates_model_rows(sources):
    from refiner.output.overview import _cost

    cost = _cost([TokenUsage(step="a", model="claude-opus-5-5", input_tokens=1_000_000, output_tokens=0),
                  TokenUsage(step="b", model="claude-opus-5-5", input_tokens=1000, output_tokens=500, subscription=True)],
                 sources.configuration)
    assert len(cost['rows']) == 2 and cost['subscription'] and not cost['subscription_only']
    assert [r['cost'] for r in cost['rows']] == ["4,00 USD", "v předplatném"]
    assert cost['total'] == "4,00"


def test_api_only_cost_has_no_subscription_flags(sources):
    from refiner.output.overview import _cost

    cost = _cost([TokenUsage(step="a", model="claude-opus-5-5", input_tokens=10, output_tokens=5)], sources.configuration)
    assert not cost['subscription'] and not cost['subscription_only']
    assert not _cost([], sources.configuration)['subscription_only']


def test_old_usage_without_subscription_is_api():
    assert TokenUsage.model_validate({'step': "x", "model": "m", 'input_tokens': 1, 'output_tokens': 1}).subscription is False


def test_overview_subscription_only_total(tmp_path, sources):
    run = make_run(tmp_path, sources)
    run.add_usage([TokenUsage(step="a", model="claude-opus-5-5", input_tokens=10, output_tokens=5, subscription=True)])
    html = _html(run, sources)
    assert "v předplatném" in html and "0,00 USD" not in html
    assert "se neúčtují po tokenech" in html


def test_overview_mixed_billing_total(tmp_path, sources):
    run = make_run(tmp_path, sources)
    run.add_usage([TokenUsage(step="a", model="claude-opus-5-5", input_tokens=1_000_000, output_tokens=0),
                         TokenUsage(step="b", model="gpt-6-astra", input_tokens=10, output_tokens=5, subscription=True)])
    html = _html(run, sources)
    assert "4,00 USD + část v předplatném" in html


def test_overview_api_only_omits_subscription_note(tmp_path, sources):
    run = make_run(tmp_path, sources)
    run.add_usage([TokenUsage(step="a", model="claude-opus-5-5", input_tokens=10, output_tokens=5)])
    assert "předplatném" not in _html(run, sources)

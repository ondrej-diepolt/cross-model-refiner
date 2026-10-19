from datetime import datetime

from refiner.data import Evaluation, TokenUsage, ScoreResult
from refiner.models.fakes import FakeModel
from refiner.loop import run_loop
from refiner.vystup.prehled import vytvor_prehled
from tests.helpers import make_run, make_evaluation, make_criteria, scripted_responses, scripted_models


def _ticho(_: str) -> None:
    pass


def _html(beh, sources) -> str:
    return vytvor_prehled(beh, sources.configuration).read_text(encoding="utf-8")


def test_prehled_dokonceneho_behu(tmp_path, sources):
    beh = make_run(tmp_path, sources)
    v = run_loop(beh, sources, *scripted_models([7.0, 9.5]), report=_ticho)
    assert v.reason == 'target_reached'
    beh.write_fixed("FINALNI_nabidka.md", "# Nabídka\n\nSazba: [DOPLNIT: sazba za MD]\n")
    beh.finish('completed', v.reason, final_version=v.final_version)
    cesta = vytvor_prehled(beh, sources.configuration)
    assert cesta == beh.directory / "prehled.html"
    html = cesta.read_text(encoding="utf-8")
    assert "Cíl splněn" in html and "FINALNI_nabidka.docx" in html
    assert "Hodnocení 1" in html and "Hodnocení 2" in html and "9,6" in html


def test_prehled_placeholder_z_finalni_verze(tmp_path, sources):
    beh = make_run(tmp_path, sources)
    run_loop(beh, sources, *scripted_models([9.5]), report=_ticho)
    beh.write_fixed("03_navrh_v1.md", "# Nabídka\n\nSazba: [DOPLNIT: sazba za MD]\n")
    beh.finish('completed', 'target_reached', final_version=1)
    assert "sazba za MD" in _html(beh, sources)


def test_prehled_odkazy_na_soubory_kroku(tmp_path, sources):
    beh = make_run(tmp_path, sources)
    v = run_loop(beh, sources, *scripted_models([7.0, 9.5]), report=_ticho)
    beh.finish('completed', v.reason, final_version=v.final_version)
    html = _html(beh, sources)
    for z in beh.state.steps.values():
        assert f'href="{z.file}"' in html
    assert 'href="04_hodnoceni_1.md"' in html
    assert "_zmeny.html" in html


def test_prehled_preruseneho_behu_bez_hodnoceni(tmp_path, sources):
    beh = make_run(tmp_path, sources)
    pisatel, hodnotitel = scripted_responses([9.5])
    pisatel['requirements'] = [RuntimeError("Spojení vypadlo")]
    try:
        run_loop(beh, sources, FakeModel(pisatel, name="c"), FakeModel(hodnotitel, name="g"),
                     report=_ticho)
    except Exception:
        pass
    beh.finish('interrupted', error="Spojení vypadlo")
    html = _html(beh, sources)
    assert "Běh byl přerušen" in html and "Spojení vypadlo" in html and "pokracovat.bat" in html


def test_prehled_bezici_stav_bez_ukonceni(tmp_path, sources):
    beh = make_run(tmp_path, sources)
    assert "prehled" in vytvor_prehled(beh, sources.configuration).name


def test_prehled_escapuje_html_z_modelu(tmp_path, sources):
    beh = make_run(tmp_path, sources)
    run_loop(beh, sources, *scripted_models([9.5]), report=_ticho)
    h = beh.data('evaluation_1', Evaluation)
    h.criteria[0].rationale = "<script>alert(1)</script>"
    h.suggestions[0].problem = "<script>alert(2)</script>"
    h.claims_to_verify = []
    beh.write_fixed("data/04_hodnoceni_1.json", h.model_dump_json())
    beh.write_fixed("03_navrh_v1.md", "# N\n\n<script>alert(3)</script> [DOPLNIT: <b>x</b>]\n")
    beh.finish('completed', 'target_reached', final_version=1)
    html = _html(beh, sources)
    assert "<script" not in html and "<b>x</b>" not in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html


def test_prehled_tvrzeni_k_overeni_escapovana(tmp_path, sources):
    from refiner.data import ClaimToVerify

    beh = make_run(tmp_path, sources)
    run_loop(beh, sources, *scripted_models([9.5]), report=_ticho)
    h = beh.data('evaluation_1', Evaluation)
    h.claims_to_verify = [ClaimToVerify(citation="<script>alert(1)</script>", reason="Zákon č. 134/2016")]
    beh.write_fixed("data/04_hodnoceni_1.json", h.model_dump_json())
    beh.finish('completed', 'target_reached', final_version=1)
    html = _html(beh, sources)
    assert "<script" not in html and "&lt;script&gt;alert(1)" in html and "134/2016" in html


def test_prehled_cena_a_tokeny(tmp_path, sources):
    beh = make_run(tmp_path, sources)
    beh.add_usage([TokenUsage(step="a", model="claude-opus-5-5", input_tokens=1_000_000, output_tokens=0),
                         TokenUsage(step="b", model="claude-opus-5-5", input_tokens=1_000_000, output_tokens=0),
                         TokenUsage(step="c", model="neznamy-model", input_tokens=10, output_tokens=5)])
    html = _html(beh, sources)
    assert "8,00" in html and "orientačně" in html and "cena neznámá" in html


def test_cena_cache_podle_poskytovatele(sources):
    """Anthropic: vstup bez cache, zápis ×1,25, čtení ×0,1. OpenAI: cache je podmnožina vstupu, ×0,5."""
    from refiner.vystup.prehled import _cena

    cena = _cena([
        # 4 + 2 000 000×0,1×4 + 400 000×1,25×4 + 100 000×20 (za milion) = 4 + 0,8 + 2 + 2 = 8,80
        TokenUsage(step="a", model="claude-opus-5-5", input_tokens=1_000_000, output_tokens=100_000,
                 cache_read_tokens=2_000_000, cache_write_tokens=400_000),
        # (1 000 000 − 600 000)×10 + 600 000×0,5×10 + 10 000×50 (za milion) = 4 + 3 + 0,5 = 7,50
        TokenUsage(step="b", model="gpt-6-astra", input_tokens=1_000_000, output_tokens=10_000, cache_read_tokens=600_000),
    ], sources.configuration)
    assert [r["cena"] for r in cena["radky"]] == ["8,80 USD", "7,50 USD"]
    assert cena["celkem"] == "16,30"


def test_prehled_cena_uvadi_odhad_cache(tmp_path, sources):
    beh = make_run(tmp_path, sources)
    beh.add_usage([TokenUsage(step="a", model="claude-opus-5-5", input_tokens=10, output_tokens=5)])
    html = _html(beh, sources)
    assert "Cena (orientačně, cache odhadem)" in html and "bez slev za cache" not in html


def test_prehled_finalni_splnila_cil_vysvetli(tmp_path, sources):
    beh = make_run(tmp_path, sources)
    beh.save_score(1, ScoreResult(a=9.5, b=9.5, c=10, total=9.5, target_met=True, unmet_reasons=[]))
    beh.save_score(2, ScoreResult(a=9.8, b=9.8, c=7, total=9.6, target_met=False,
                                    unmet_reasons=["text obsahuje vymyšlené fakty (1)"]))
    beh.finish('completed', 'target_reached', final_version=1)
    html = _html(beh, sources)
    assert "verze 1 splnila cíl" in html and "vyšší skóre" not in html


def test_prehled_finalni_neni_posledni_vysvetli(tmp_path, sources):
    beh = make_run(tmp_path, sources)
    for k, c in enumerate([6.0, 8.0, 7.0, 7.5], start=1):
        beh.save_score(k, ScoreResult(a=c, b=c, c=10, total=c, target_met=False, unmet_reasons=[]))
    beh.finish('completed', 'revision_limit', final_version=2)
    html = _html(beh, sources)
    assert "vyšší skóre" in html and "verze 2" in html and "Vyčerpán limit" in html


def test_prehled_tabulka_kriterii_a_barvy(tmp_path, sources):
    beh = make_run(tmp_path, sources)
    v = run_loop(beh, sources, *scripted_models([6.0, 9.5]), report=_ticho)
    beh.finish('completed', v.reason, final_version=v.final_version)
    html = _html(beh, sources)
    assert "Celkem" in html and "N1" in html and "B1" in html
    assert "s-cervena" in html and "s-zelena" in html


def test_prehled_stats_navrhu_a_dalsi_kola(tmp_path, sources):
    beh = make_run(tmp_path, sources)
    run_loop(beh, sources, *scripted_models([7.0] * 4, decision='partial'), report=_ticho)
    beh.finish('completed', 'revision_limit', final_version=2)
    assert "Částečně" in _html(beh, sources)


def test_cena_predplatne_se_nepocita(sources):
    from refiner.vystup.prehled import _cena, _desetinne

    cena = _cena([TokenUsage(step='suggestion', model="claude-opus-5-5", input_tokens=1000, output_tokens=500, subscription=True),
                  TokenUsage(step='evaluation_1', model="gpt-6-astra", input_tokens=1000, output_tokens=500, subscription=True)],
                 sources.configuration)
    assert [r["cena"] for r in cena["radky"]] == ["v předplatném", "v předplatném"]
    assert cena["jen_predplatne"] and cena["predplatne"] and not cena["neznama"]
    assert cena["celkem"] == _desetinne(0.0)


def test_cena_smiseny_beh_rozdeli_radky(sources):
    from refiner.vystup.prehled import _cena

    cena = _cena([TokenUsage(step="a", model="claude-opus-5-5", input_tokens=1_000_000, output_tokens=0),
                  TokenUsage(step="b", model="claude-opus-5-5", input_tokens=1000, output_tokens=500, subscription=True)],
                 sources.configuration)
    assert len(cena["radky"]) == 2 and cena["predplatne"] and not cena["jen_predplatne"]
    assert [r["cena"] for r in cena["radky"]] == ["4,00 USD", "v předplatném"]
    assert cena["celkem"] == "4,00"


def test_cena_jen_api_nema_priznaky_predplatneho(sources):
    from refiner.vystup.prehled import _cena

    cena = _cena([TokenUsage(step="a", model="claude-opus-5-5", input_tokens=10, output_tokens=5)], sources.configuration)
    assert not cena["predplatne"] and not cena["jen_predplatne"]
    assert not _cena([], sources.configuration)["jen_predplatne"]


def test_stara_spotreba_bez_pole_je_api():
    assert TokenUsage.model_validate({'step': "x", "model": "m", "vstup": 1, "vystup": 1}).subscription is False


def test_prehled_celkem_v_predplatnem(tmp_path, sources):
    beh = make_run(tmp_path, sources)
    beh.add_usage([TokenUsage(step="a", model="claude-opus-5-5", input_tokens=10, output_tokens=5, subscription=True)])
    html = _html(beh, sources)
    assert "v předplatném" in html and "0,00 USD" not in html
    assert "se neúčtují po tokenech" in html


def test_prehled_celkem_smiseny(tmp_path, sources):
    beh = make_run(tmp_path, sources)
    beh.add_usage([TokenUsage(step="a", model="claude-opus-5-5", input_tokens=1_000_000, output_tokens=0),
                         TokenUsage(step="b", model="gpt-6-astra", input_tokens=10, output_tokens=5, subscription=True)])
    html = _html(beh, sources)
    assert "4,00 USD + část v předplatném" in html


def test_prehled_jen_api_bez_poznamky_o_predplatnem(tmp_path, sources):
    beh = make_run(tmp_path, sources)
    beh.add_usage([TokenUsage(step="a", model="claude-opus-5-5", input_tokens=10, output_tokens=5)])
    assert "předplatném" not in _html(beh, sources)

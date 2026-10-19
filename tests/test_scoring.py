from refiner.data import Requirement, ScoreResult, build_criteria
from refiner.configuration import ProfileCriterion
from refiner.scoring import format_score, fact_score, calculate_score, select_final_version
from tests.helpers import make_evaluation, make_criteria, make_settings


def test_fact_score():
    assert [fact_score(n) for n in (0, 1, 2, 3, 4)] == [10, 7, 4, 1, 1]


def test_weighted_score_rounds_half_up():
    # 0.5*9 + 0.35*9 + 0.15*10 = 9.15 -> 9.2
    v = calculate_score(make_evaluation(9.0), make_criteria(), make_settings())
    assert (v.a, v.b, v.c, v.total) == (9.0, 9.0, 10.0, 9.2)


def test_group_b_is_weighted_average():
    others = {f"B{i}": 8.0 for i in range(2, 7)}
    v = calculate_score(make_evaluation(8.0, {"B1": 10.0, **others}), make_criteria(), make_settings())
    assert v.b == 8.5


def test_target_met():
    v = calculate_score(make_evaluation(9.5), make_criteria(), make_settings())
    assert v.total == 9.6 and v.target_met and v.unmet_reasons == []


def test_requirement_below_minimum_blocks_target():
    v = calculate_score(make_evaluation(10.0, {"N2": 7.5}), make_criteria(), make_settings())
    assert not v.target_met
    assert any("N2" in d for d in v.unmet_reasons)


def test_fabricated_fact_blocks_target():
    v = calculate_score(make_evaluation(10.0, facts=1), make_criteria(), make_settings())
    assert v.total == 9.6 and not v.target_met
    assert any("vymyšlen" in d for d in v.unmet_reasons)


def test_total_below_target():
    v = calculate_score(make_evaluation(9.2), make_criteria(), make_settings())
    assert v.total == 9.3 and not v.target_met
    assert any("9,3 < 9,5" in d for d in v.unmet_reasons)


def _score_result(total: float, target: bool = False) -> ScoreResult:
    return ScoreResult(a=total, b=total, c=10, total=total, target_met=target,
                         unmet_reasons=[] if target else ["x"])


def test_final_version_prefers_highest_score_then_later_version():
    """Without a met target, choose the highest score and break ties with the later version."""
    assert select_final_version({1: _score_result(7.0), 2: _score_result(8.8), 3: _score_result(8.1), 4: _score_result(8.8)}) == 4
    assert select_final_version({1: _score_result(7.0), 2: _score_result(8.8), 3: _score_result(8.1)}) == 2


def test_final_version_prefers_met_target_over_higher_score():
    """Version 2 scores 9.6 but is blocked; version 3 meets the target with 9.5."""
    assert select_final_version({1: _score_result(8.0), 2: _score_result(9.6), 3: _score_result(9.5, target=True)}) == 3


def test_final_version_breaks_target_tie_with_later_version():
    assert select_final_version({1: _score_result(9.6, target=True), 2: _score_result(9.6, target=True)}) == 2
    assert select_final_version({1: _score_result(9.7, target=True), 2: _score_result(9.6, target=True), 3: _score_result(9.9)}) == 1


def test_format_score():
    assert format_score(9.5) == "9,5" and format_score(10.0) == "10,0"


def test_build_criteria_order_and_groups():
    requirements = [Requirement(id=f"N{i}", text=f"text {i}", citation=f"cit {i}") for i in (1, 2)]
    profile = [ProfileCriterion(id="B1", name="n", description="p", weight=0.4)]
    k = build_criteria(requirements, profile)
    assert [x.id for x in k] == ["N1", "N2", "B1"]
    assert [x.group for x in k] == ["A", "A", "B"]
    assert k[0].name == "text 1" and k[0].description == "cit 1" and k[0].weight == 1
    assert k[2].weight == 0.4

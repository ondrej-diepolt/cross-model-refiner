import pytest
from pydantic import BaseModel

from refiner.models.fakes import FakeModel


class Schema(BaseModel):
    a: int


def test_json_dict_validates_against_schema():
    m = FakeModel({'step': [{"a": 1}]})
    assert m.json("i", "z", Schema, step='step') == Schema(a=1)


def test_json_basemodel_and_text_str():
    m = FakeModel({"j": [Schema(a=2)], "t": ["ahoj"]})
    assert m.json("i", "z", Schema, step="j").a == 2
    assert m.text("i", "z", step="t") == "ahoj"


def test_exact_key_precedes_prefix():
    m = FakeModel({'evaluation_2': [{"a": 1}], 'evaluation': [{"a": 2}]})
    assert m.json("i", "z", Schema, step='evaluation_2').a == 1
    assert m.json("i", "z", Schema, step='evaluation_3').a == 2


def test_exception_is_raised():
    m = FakeModel({"k": [RuntimeError("boom")]})
    with pytest.raises(RuntimeError, match="boom"):
        m.text("i", "z", step="k")


def test_keyboardinterrupt_is_raised():
    m = FakeModel({"k": [KeyboardInterrupt()]})
    with pytest.raises(KeyboardInterrupt):
        m.text("i", "z", step="k")


def test_callable_receives_instructions_and_task():
    m = FakeModel({"k": [lambda i, z: f"{i}|{z}"]})
    assert m.text("INS", "ZAD", step="k") == "INS|ZAD"
    assert m.calls == [("k", "INS", "ZAD")]


def test_exhausted_responses_assertion():
    m = FakeModel({"k": ["x"]})
    m.text("i", "z", step="k")
    with pytest.raises(AssertionError, match="Fake model has no response for step"):
        m.text("i", "z", step="k")
    with pytest.raises(AssertionError):
        m.text("i", "z", step="jiny")


def test_usage_is_taken_and_cleared():
    m = FakeModel({"k": ["x", "y"]}, name="f")
    m.text("i", "z", step="k")
    m.text("i", "z", step="k")
    s = m.take_usage()
    assert len(s) == 2
    assert (s[0].step, s[0].model, s[0].input_tokens, s[0].output_tokens) == ("k", "f", 1000, 500)
    assert m.take_usage() == []

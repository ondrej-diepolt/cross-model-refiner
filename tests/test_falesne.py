import pytest
from pydantic import BaseModel

from refiner.modely.falesne import FalesnyModel


class Schema(BaseModel):
    a: int


def test_json_dict_se_validuje_do_schematu():
    m = FalesnyModel({"krok": [{"a": 1}]})
    assert m.json("i", "z", Schema, krok="krok") == Schema(a=1)


def test_json_basemodel_a_text_str():
    m = FalesnyModel({"j": [Schema(a=2)], "t": ["ahoj"]})
    assert m.json("i", "z", Schema, krok="j").a == 2
    assert m.text("i", "z", krok="t") == "ahoj"


def test_presny_klic_ma_prednost_pred_prefixem():
    m = FalesnyModel({"hodnoceni_2": [{"a": 1}], "hodnoceni": [{"a": 2}]})
    assert m.json("i", "z", Schema, krok="hodnoceni_2").a == 1
    assert m.json("i", "z", Schema, krok="hodnoceni_3").a == 2


def test_vyjimka_se_vyhodi():
    m = FalesnyModel({"k": [RuntimeError("boom")]})
    with pytest.raises(RuntimeError, match="boom"):
        m.text("i", "z", krok="k")


def test_keyboardinterrupt_se_vyhodi():
    m = FalesnyModel({"k": [KeyboardInterrupt()]})
    with pytest.raises(KeyboardInterrupt):
        m.text("i", "z", krok="k")


def test_callable_dostane_instrukce_a_zadani():
    m = FalesnyModel({"k": [lambda i, z: f"{i}|{z}"]})
    assert m.text("INS", "ZAD", krok="k") == "INS|ZAD"
    assert m.volani == [("k", "INS", "ZAD")]


def test_vycerpane_odpovedi_assertion():
    m = FalesnyModel({"k": ["x"]})
    m.text("i", "z", krok="k")
    with pytest.raises(AssertionError, match="Falešný model nemá odpověď pro krok"):
        m.text("i", "z", krok="k")
    with pytest.raises(AssertionError):
        m.text("i", "z", krok="jiny")


def test_spotreba_se_vyzvedne_a_vyprazdni():
    m = FalesnyModel({"k": ["x", "y"]}, nazev="f")
    m.text("i", "z", krok="k")
    m.text("i", "z", krok="k")
    s = m.vyzvedni_spotrebu()
    assert len(s) == 2
    assert (s[0].krok, s[0].model, s[0].vstup, s[0].vystup) == ("k", "f", 1000, 500)
    assert m.vyzvedni_spotrebu() == []

"""Testy deterministické kontroly faktů."""
from refiner.fakta import najdi_placeholdery, podezrele_udaje


def test_placeholdery():
    md = "Cena [DOPLNIT: sazba za MD] … IČ [DOPLNIT: IČ] … [DOPLNIT: sazba za MD] … [DOPLNIT]"
    assert najdi_placeholdery(md) == ["sazba za MD", "IČ", ""]


def test_podezrele_castky_a_ico():
    zdroje = "Sazba 15 000 Kč za MD."
    dok = "Sazba 15 000 Kč. Cena 187 500 Kč. IČ 12345678. Kontakt jan@firma.cz, +420 777 123 456."
    druhy = {(u.druh, u.hodnota) for u in podezrele_udaje(dok, zdroje)}
    assert ("castka", "187 500 Kč") in druhy and not any(h.startswith("15 000") for _, h in druhy)
    assert {"ico", "email", "telefon"} <= {d for d, _ in druhy}


def test_podezrele_jmeno_s_titulem():
    u = podezrele_udaje("Vedoucí: Ing. Jan Novák.", "Nic.")
    assert ("jmeno", "Ing. Jan Novák") in {(x.druh, x.hodnota) for x in u}
    assert podezrele_udaje("Vedoucí: Ing. Jan Novák.", "Ing. Jan Novák je kontakt") == []


def test_nbsp_ve_zdroji_se_shoduje():
    assert podezrele_udaje("Sazba 15 000 Kč.", "Sazba 15 000 Kč.") == []
    assert podezrele_udaje("Sazba 15 000 Kč.", "Sazba 15 000 Kč.") == []


def test_placeholder_neni_podezrely():
    assert podezrele_udaje("[DOPLNIT: IČ 12345678]", "") == []


def test_url():
    u = podezrele_udaje("Viz https://example.cz/x", "")
    assert [(x.druh, x.hodnota) for x in u] == [("url", "https://example.cz/x")]

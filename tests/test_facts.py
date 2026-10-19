"""Tests for deterministic fact checks."""
from refiner.facts import find_placeholders, find_suspicious_facts


def test_placeholders():
    md = "Cena [DOPLNIT: sazba za MD] … IČ [DOPLNIT: IČ] … [DOPLNIT: sazba za MD] … [DOPLNIT]"
    assert find_placeholders(md) == ["sazba za MD", "IČ", ""]


def test_suspicious_amounts_and_company_ids():
    sources = "Sazba 15 000 Kč za MD."
    document = "Sazba 15 000 Kč. Cena 187 500 Kč. IČ 12345678. Kontakt jan@firma.cz, +420 777 123 456."
    kinds = {(u.kind, u.value) for u in find_suspicious_facts(document, sources)}
    assert ('amount', "187 500 Kč") in kinds and not any(h.startswith("15 000") for _, h in kinds)
    assert {'company_id', "email", 'phone'} <= {d for d, _ in kinds}


def test_suspicious_name_with_title():
    u = find_suspicious_facts("Vedoucí: Ing. Jan Novák.", "Nic.")
    assert ('name', "Ing. Jan Novák") in {(x.kind, x.value) for x in u}
    assert find_suspicious_facts("Vedoucí: Ing. Jan Novák.", "Ing. Jan Novák je kontakt") == []


def test_nbsp_matches_source():
    assert find_suspicious_facts("Sazba 15 000 Kč.", "Sazba 15 000 Kč.") == []
    assert find_suspicious_facts("Sazba 15 000 Kč.", "Sazba 15 000 Kč.") == []


def test_placeholder_is_not_suspicious():
    assert find_suspicious_facts("[DOPLNIT: IČ 12345678]", "") == []


def test_url():
    u = find_suspicious_facts("Viz https://example.cz/x", "")
    assert [(x.kind, x.value) for x in u] == [("url", "https://example.cz/x")]

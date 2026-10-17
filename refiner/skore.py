"""Výpočet skóre a splnění cíle; počítá výhradně kód, nikdy model."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from refiner.data import Hodnoceni, Kriterium, VysledekSkore
from refiner.konfigurace import Nastaveni

_DESETINA = Decimal("0.1")


def _d(x: float) -> Decimal:
    return Decimal(str(x))


def _zaokrouhli(x: Decimal) -> Decimal:
    return x.quantize(_DESETINA, rounding=ROUND_HALF_UP)


def format_skore(x: float) -> str:
    return f"{_zaokrouhli(_d(x))}".replace(".", ",")


def skore_c(pocet_faktu: int) -> float:
    """10 bez vymyšlených faktů, jinak max(1, 10 − 3×počet)."""
    if pocet_faktu <= 0:
        return 10.0
    return float(max(1, 10 - 3 * pocet_faktu))


def spocitej(hodnoceni: Hodnoceni, kriteria: list[Kriterium], nastaveni: Nastaveni) -> VysledekSkore:
    skore = {s.id: _d(s.skore) for s in hodnoceni.kriteria}
    a_krit = [k for k in kriteria if k.skupina == "A" and k.id in skore]
    b_krit = [k for k in kriteria if k.skupina == "B" and k.id in skore]

    a = sum((skore[k.id] for k in a_krit), Decimal(0)) / len(a_krit) if a_krit else Decimal(0)
    soucet_vah = sum((_d(k.vaha) for k in b_krit), Decimal(0))
    b = sum((skore[k.id] * _d(k.vaha) for k in b_krit), Decimal(0)) / soucet_vah if soucet_vah else Decimal(0)
    pocet_faktu = len(hodnoceni.vymyslena_fakta)
    c = _d(skore_c(pocet_faktu))

    v = nastaveni.vahy_skupin
    celkem = _zaokrouhli(_d(v["A"]) * a + _d(v["B"]) * b + _d(v["C"]) * c)

    duvody: list[str] = []
    cil = _d(nastaveni.smycka.cilove_skore)
    if celkem < cil:
        duvody.append(f"celkové skóre {format_skore(float(celkem))} < {format_skore(float(cil))}")
    minimum = _d(nastaveni.smycka.min_nalezitost)
    for k in a_krit:
        if skore[k.id] < minimum:
            duvody.append(
                f"náležitost {k.id} má skóre {format_skore(float(skore[k.id]))}, "
                f"minimum je {format_skore(float(minimum))}"
            )
    if pocet_faktu > 0:
        duvody.append(f"text obsahuje vymyšlené fakty ({pocet_faktu})")

    return VysledekSkore(
        a=float(_zaokrouhli(a)),
        b=float(_zaokrouhli(b)),
        c=float(c),
        celkem=float(celkem),
        cil_splnen=not duvody,
        duvody_nesplneni=duvody,
    )


def vyber_finalni(celkova_skore: dict[int, float]) -> int:
    """Verze s nejvyšším skóre; při shodě pozdější."""
    return max(celkova_skore, key=lambda verze: (celkova_skore[verze], verze))

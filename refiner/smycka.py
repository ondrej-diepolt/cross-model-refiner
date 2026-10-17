"""Řízení smyčky návrh → hodnocení → posouzení → zapracování (design kap. 3.3) s obnovením z disku."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from refiner.beh import Beh
from refiner.data import (
    Hodnoceni,
    Navrh,
    Posouzeni,
    Rozhodnuti,
    VysledekSkore,
    VystupNalezitosti,
    sestav_kriteria,
)
from refiner.kroky import (
    Zdroje,
    extrahuj_nalezitosti,
    napis_navrh,
    ohodnot,
    posud,
    prijate,
    zapracuj,
)
from refiner.modely.rozhrani import Model
from refiner.skore import format_skore, spocitej, vyber_finalni
from refiner.vystup.diff import diff_html
from refiner.vystup.markdown import hodnoceni_md, nalezitosti_md, posouzeni_md

DuvodUkonceni = Literal["cil_splnen", "limit_revizi", "zadna_zmena"]


@dataclass
class VysledekBehu:
    duvod: DuvodUkonceni
    finalni_verze: int
    skore: dict[int, VysledekSkore]   # klíč = číslo hodnocení = číslo hodnocené verze


def _odmitnute(h: Hodnoceni, p: Posouzeni) -> list[tuple[Navrh, Rozhodnuti]]:
    """Odmítnuté návrhy jednoho kola; ID návrhů platí jen v rámci svého hodnocení."""
    podle_id = {n.id: n for n in h.navrhy}
    return [
        (podle_id[r.id_navrhu], r)
        for r in p.rozhodnuti
        if r.rozhodnuti == "odmitnuto" and r.id_navrhu in podle_id
    ]


def spust_smycku(
    beh: Beh,
    zdroje: Zdroje,
    pisatel: Model,
    hodnotitel: Model,
    hlaseni: Callable[[str], None],
) -> VysledekBehu:
    """Provede smyčku; hotové kroky z `beh` načte místo volání modelu. Výjimky nechytá."""
    nastaveni = zdroje.konfigurace.nastaveni
    max_revizi = nastaveni.smycka.max_revizi
    celkem_kroku = 2 + 3 * max_revizi + 1

    def ohlas(poradi: int, popis: str) -> None:
        hlaseni(f"[{poradi}/{celkem_kroku}] {popis}…")

    def uloz_spotrebu() -> None:
        beh.pridej_spotrebu(pisatel.vyzvedni_spotrebu() + hodnotitel.vyzvedni_spotrebu())

    # Krok 0 – náležitosti
    if beh.hotovo("nalezitosti"):
        nalezitosti = beh.data("nalezitosti", VystupNalezitosti).nalezitosti
    else:
        ohlas(1, "Náležitosti z poptávky")
        nalezitosti, varovani = extrahuj_nalezitosti(pisatel, zdroje)
        beh.zapis("nalezitosti", "nalezitosti.md", nalezitosti_md(nalezitosti, varovani),
                  data=VystupNalezitosti(nalezitosti=nalezitosti))
        for v in varovani:
            beh.pridej_varovani(v)
        uloz_spotrebu()
    kriteria = sestav_kriteria(nalezitosti, zdroje.konfigurace.kriteria_profilu)

    # Krok 1 – návrh v1
    if beh.hotovo("navrh_1"):
        dokument = beh.text("navrh_1")
    else:
        ohlas(2, "Návrh v1")
        dokument = napis_navrh(pisatel, zdroje, nalezitosti)
        beh.zapis("navrh_1", "navrh_v1.md", dokument)
        uloz_spotrebu()

    skore: dict[int, VysledekSkore] = {}
    odmitnute: list[tuple[Navrh, Rozhodnuti]] = []

    def konec(duvod: DuvodUkonceni) -> VysledekBehu:
        finalni = vyber_finalni({verze: s.celkem for verze, s in skore.items()})
        return VysledekBehu(duvod=duvod, finalni_verze=finalni, skore=dict(skore))

    k = 1
    while True:
        poradi = 3 + 3 * (k - 1)
        zaverecne = k == max_revizi + 1

        # Hodnocení k (verze vk)
        krok = f"hodnoceni_{k}"
        if beh.hotovo(krok):
            h = beh.data(krok, Hodnoceni)
            vysledek = beh.stav.skore.get(str(k))
            if vysledek is None:   # pád mezi zápisem hodnocení a uložením skóre
                vysledek = spocitej(h, kriteria, nastaveni)
                beh.uloz_skore(k, vysledek)
        else:
            ohlas(poradi, f"Hodnocení {k}" + (" (závěrečné)" if zaverecne else ""))
            h, varovani = ohodnot(hodnotitel, zdroje, kriteria, dokument, odmitnute, krok)
            vysledek = spocitej(h, kriteria, nastaveni)
            beh.zapis(krok, f"hodnoceni_{k}.md", hodnoceni_md(k, h, vysledek, kriteria), data=h)
            beh.uloz_skore(k, vysledek)
            for v in varovani:
                beh.pridej_varovani(v)
            uloz_spotrebu()
            hlaseni(f"hotovo, skóre {format_skore(vysledek.celkem)}")
        skore[k] = vysledek

        if vysledek.cil_splnen:
            return konec("cil_splnen")
        if zaverecne:
            return konec("limit_revizi")

        # Posouzení k
        krok = f"posouzeni_{k}"
        if beh.hotovo(krok):
            p = beh.data(krok, Posouzeni)
        else:
            ohlas(poradi + 1, f"Posouzení návrhů z hodnocení {k}")
            p = posud(pisatel, zdroje, nalezitosti, dokument, h, krok)
            beh.zapis(krok, f"posouzeni_{k}.md", posouzeni_md(k, h, p), data=p)
            uloz_spotrebu()
        odmitnute += _odmitnute(h, p)

        if not prijate(p):
            return konec("zadna_zmena")

        # Zapracování k → verze k+1
        krok = f"navrh_{k + 1}"
        if beh.hotovo(krok):
            dokument = beh.text(krok)
        else:
            ohlas(poradi + 2, f"Zapracování přijatých návrhů → v{k + 1}")
            novy = zapracuj(pisatel, zdroje, nalezitosti, dokument, h, p, krok)
            beh.zapis(krok, f"navrh_v{k + 1}.md", novy)
            beh.zapis_k(krok, f"navrh_v{k + 1}_zmeny.html",
                        diff_html(dokument, novy, f"Verze {k}", f"Verze {k + 1}"))
            uloz_spotrebu()
            dokument = novy
        k += 1

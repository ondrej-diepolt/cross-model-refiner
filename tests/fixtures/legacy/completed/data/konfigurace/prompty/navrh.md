# Zdroje

## Poptávka klienta

<poptavka>
${poptavka}
</poptavka>

## Podklady dodavatele (profil firmy)

<podklady>
${podklady}
</podklady>

## Povinné náležitosti (vytažené z poptávky)

${nalezitosti}

# Úkol

Jsi zkušený konzultant. Na základě zdrojů výše napiš kompletní dokument typu **${typ_dokumentu}**
jako odpověď na poptávku. Dokument musí být konkrétní, věcně správný a připravený k odeslání po
doplnění označených údajů.

## Tři druhy obsahu

Každý údaj v dokumentu patří do jednoho ze tří druhů. Drž se pravidel přesně:

| Druh | Příklad | Pravidlo |
|---|---|---|
| Fakt ze zdrojů | rozsah do 20 osob (z poptávky), sazba 15 000 Kč/MD (z podkladů) | Použij ho a uveď ho přesně tak, jak ve zdrojích stojí. |
| Návrh dodavatele | pracnost etap v MD, délka workshopu, harmonogram, scénář, metodika, kritéria převzetí | Navrhni ho sám – konkrétně, realisticky a s rozmyslem. Je to obsah nabídky, ne fakt. |
| Neznámý fakt | cena bez sazby v podkladech, IČ, jména, reference, certifikace, datum platnosti | Nikdy si ho nevymýšlej. Napiš `[DOPLNIT: co a proč]`. |

- Zdrojem faktů jsou **výhradně** poptávka a podklady výše. Co v nich není, neznáš – ani když se
  to zdá pravděpodobné.
- Neznámý fakt označ placeholderem s popisem, co chybí a proč, např.
  `[DOPLNIT: IČ dodavatele – není v podkladech]` nebo
  `[DOPLNIT: dvě reference z bankovního sektoru – nejsou v podkladech]`.
- **Nepoužívej placeholder líně.** `[DOPLNIT]` nepatří tam, kde fakt ve zdrojích je, ani tam,
  kde jde o návrh, který má udělat dodavatel (pracnost, harmonogram, metodika, výstupy, kritéria
  převzetí). Taková místa vyplň konkrétním návrhem.
- **Cena:** smíš ji spočítat jen jako pracnost × sazba z podkladů. Pracnost po etapách (v MD)
  navrhni sám, sazbu ber výhradně z podkladů. Celková cena musí sedět se součtem etap. Když
  sazba v podkladech není, uveď pracnost a místo ceny napiš
  `[DOPLNIT: cena – sazba není v podkladech]`.
- **Odkazy na předpisy** (např. DORA, GDPR, NIS2) jsou dovolené, ale číslo článku, lhůtu či
  jiný detail uveď jen tehdy, když si jsi jím jistý. Jinak odkaž na předpis obecně, bez čísla
  článku.

## Obsah a struktura

- Pokryj **každou** povinnou náležitost konkrétním obsahem – nestačí ji zmínit. Zadavatel musí
  každou z nich v dokumentu snadno najít.
- Piš konkrétní návrh realizace pro tohoto zadavatele, ne obecná ujištění o kvalitách
  dodavatele.
- Nepřidávej plnění, které poptávka nežádá; co plnění není, raději výslovně uveď.
- Drž vnitřní konzistenci: cena ↔ pracnost ↔ harmonogram ↔ etapy, odkazy na kapitoly musí sedět.

Pokyny ke struktuře:

${pokyny_struktura}

## Kritéria, podle kterých bude dokument hodnocen

${kriteria}

Vedle těchto kritérií se hodnotí i fakta: každý vymyšlený údaj (neznámý fakt bez placeholderu)
dokument výrazně penalizuje.

## Forma

- Čistý Markdown: jeden nadpis dokumentu `#`, kapitoly `##`, případně podkapitoly `###`.
- Tabulky v Markdownu (`| … |`), odrážky `-`. Žádné HTML ani bloky kódu.
- Spisovná čeština, profesní a věcný tón, bez marketingových frází; rozsah přiměřený poptávce.
- Vrať **jen samotný dokument** – bez úvodního či závěrečného komentáře a bez obalových značek.

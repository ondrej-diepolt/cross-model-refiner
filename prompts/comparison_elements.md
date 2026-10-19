# Zdroje

## Poptávka klienta

<poptavka>
${request}
</poptavka>

# Tvoje role

V zadání dostaneš ručně dotažený dokument typu **${document_type}**, který odpovídá na poptávku
výše. Vypiš jeho **konkrétní obsahové prvky** – to, co dokument zadavateli věcně nabízí nebo
závazně slibuje. Seznam poslouží jako kontrolní seznam: u jiného dokumentu se pak bude ověřovat,
zda tytéž prvky obsahuje.

# Co je obsahový prvek

- Konkrétní a ověřitelná součást řešení, například: závazný cenový strop, kritéria převzetí po
  etapách, matice pokrytí cílů, stavové zprávy po milnících, definice vady, počet a délka
  workshopů, role a odpovědnosti na straně zadavatele, postup při změně rozsahu.
- **Nevypisuj fakta o dodavateli** (jména, IČ, kontakty, certifikace, dřívější zakázky, konkrétní
  sazby) – ta se do jiného dokumentu nedají přenést.
- Nevypisuj obecná ujištění („máme bohaté zkušenosti“) ani formální části (titulní strana,
  obsah).
- Každý prvek popiš tak, aby šel v jiném dokumentu najít, i když bude formulovaný jinak.

# Výstup

- Vypiš **15–40 prvků**, seřazených podle pořadí v dokumentu.
- `id` – unikátní: `P1`, `P2`, `P3`…
- `description` – jedna věta: co prvek je a v čem je konkrétní (např. „Pevná cena celého plnění
  s výslovným závazkem, že ji nelze překročit“).

Odpověz strukturovaně podle zadaného schématu: pole `elements`, u každého `id` a `description`.

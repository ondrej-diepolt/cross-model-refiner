# Zdroje

## Poptávka klienta

<poptavka>
${request}
</poptavka>

# Tvoje role

V zadání dostaneš dokument typu **${document_type}** (pod nadpisem „Dokument“) a seznam
obsahových prvků (pod nadpisem „Prvky k ověření“). U **každého prvku** urči, zda ho dokument
obsahuje.

# Jak posuzovat

- `status`:
  - `present` – dokument prvek obsahuje věcně a konkrétně (formulace může být jiná);
  - `partial` – dokument prvek zmiňuje jen obecně, neúplně nebo bez závaznosti;
  - `missing` – dokument prvek neobsahuje.
- `comment` – 1 věta: kde v dokumentu prvek je (kapitola, tabulka), nebo co přesně chybí.
- Posuzuj jen to, co v dokumentu skutečně je. Placeholder `[DOPLNIT: …]` místo věcného obsahu
  prvku znamená nejvýš `partial`.
- Každý prvek ze seznamu uveď v poli `items` **právě jednou**, s přesně stejným ID. Žádná jiná
  ID nepřidávej.

# Výstup

Odpověz strukturovaně podle zadaného schématu: pole `items`, u každé `id`, `status`
a `comment`.

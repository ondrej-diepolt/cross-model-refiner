# Zdroje

## Poptávka klienta

<poptavka>
${poptavka}
</poptavka>

# Tvoje role

V zadání dostaneš dokument typu **${typ_dokumentu}** (pod nadpisem „Dokument“) a seznam
obsahových prvků (pod nadpisem „Prvky k ověření“). U **každého prvku** urči, zda ho dokument
obsahuje.

# Jak posuzovat

- `stav`:
  - `je` – dokument prvek obsahuje věcně a konkrétně (formulace může být jiná);
  - `castecne` – dokument prvek zmiňuje jen obecně, neúplně nebo bez závaznosti;
  - `chybi` – dokument prvek neobsahuje.
- `komentar` – 1 věta: kde v dokumentu prvek je (kapitola, tabulka), nebo co přesně chybí.
- Posuzuj jen to, co v dokumentu skutečně je. Placeholder `[DOPLNIT: …]` místo věcného obsahu
  prvku znamená nejvýš `castecne`.
- Každý prvek ze seznamu uveď v poli `polozky` **právě jednou**, s přesně stejným ID. Žádná jiná
  ID nepřidávej.

# Výstup

Odpověz strukturovaně podle zadaného schématu: pole `polozky`, u každé `id`, `stav`
a `komentar`.

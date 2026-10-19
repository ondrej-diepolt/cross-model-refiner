# Cross-model refiner – návrh prototypu

Datum: 2026-10-17 · Stav: návrh k odsouhlasení · Implementační plán bude samostatný dokument.

## 1. Cíl a měřítko úspěchu

Nástroj v Pythonu, který z poptávky klienta vytvoří nabídku (později i interní směrnici) střídáním
dvou modelů: Claude píše a reviduje, GPT hodnotí a navrhuje úpravy.

Prototyp je úspěšný, když platí obojí:

1. **Smyčka funguje** – běh proběhne bez zásahu člověka, skončí ze správného důvodu, při chybě API
   nic neztratí a výstupní složka srozumitelně ukazuje, co se v každém kroku stalo.
2. **Dokument je reálně použitelný** – po porovnání s ručně dotaženou referenční nabídkou
   (`examples/Nabidka_NRB_tabletop_v8.docx`) konzultant řekne, že po doplnění placeholderů a menší
   redakci by ho odeslal. Hlavní metrika: odhad minut práce do odeslatelné verze (kap. 11).

## 2. Přehled rozhodnutí

| Téma | Rozhodnutí |
|---|---|
| Iterace | Iterace = hodnocení GPT + revize Claude. Max **3 revize**; po poslední revizi proběhne **závěrečné hodnocení** bez revize (celkem max 4 hodnocení). Konec dřív, jakmile je splněn cíl. |
| Finální dokument | Verze s nejvyšším celkovým skóre (při shodě pozdější), ne automaticky poslední. |
| Fakta o dodavateli | Volitelná složka `podklady/` s profilem firmy. Co tam je, je fakt; co chybí, je `[DOPLNIT: …]`. |
| Vstup | DOCX, MD, TXT. DOCX se převádí do Markdownu přes pandoc (zachová tabulky a odrážky). PDF až později. |
| Výstup | Uvnitř smyčky Markdown. Finální dokument navíc DOCX (pandoc, volitelně se šablonou stylů). Souhrnný přehled `prehled.html`. |
| Modely | Claude `claude-opus-5-5`, GPT `gpt-6-astra`; obojí v `nastaveni.yaml`. |
| Skóre | GPT hodnotí každé kritérium zvlášť do JSON (structured outputs); celkové skóre a splnění cíle počítá kód. |
| Kritéria bez zásahu do kódu | YAML profily dokumentů + volitelný soubor kritérií vedle konkrétní poptávky + prompty v `.md` souborech. |
| Anonymizace | V prototypu ne; vědomé rozhodnutí s upozorněním (kap. 13). |
| Ovládání | Soubor do `input/`, dvojklik na `spustit.bat`. Bez GUI. |

## 3. Výklad zadání

Původní zadání: (1) připrav dokument, (2) GPT dá skóre 1–10 a navrhne úpravy, (3) relevantní změny
zohledni sokratovsky, (4) opakuj 2–3, dokud skóre < 9,5, max 3 iterace.

### 3.1 Kroky běhu

| Krok | Model | Co dělá | Výstup |
|---|---|---|---|
| 0 Náležitosti | Claude | Vytáhne z poptávky povinné náležitosti (seznam „Nabídka proto musí obsahovat…“, „Žádáme o zaslání…“ a další explicitní požadavky). Každá položka musí mít doslovnou citaci z poptávky. | seznam položek N1…Nn |
| 1 Návrh | Claude | Napíše dokument podle poptávky, profilu firmy, náležitostí a profilu dokumentu. | verze v1 |
| 2 Hodnocení | GPT | Ohodnotí každé kritérium 1–10 se zdůvodněním, vypíše vymyšlená fakta a navrhne konkrétní úpravy. | hodnocení k |
| 3a Sokratovské posouzení | Claude | U každého návrhu odpoví na tři otázky a rozhodne přijmout / přijmout částečně / odmítnout. | rozhodnutí k |
| 3b Zapracování | Claude | Zapracuje jen přijaté (a částečně přijaté) návrhy, jinak dokument nemění. | verze k+1 |
| Závěrečné hodnocení | GPT | Hodnocení po 3. revizi, bez další revize. | hodnocení 4 |

Krok 3 je rozdělený na dvě volání záměrně. Rozhodnutí jsou pak samostatný, strojově ověřitelný
záznam (ke každému návrhu existuje právě jedno rozhodnutí). A přepis dostane jen to, co prošlo,
a nemíchá se mu do něj úvaha o odmítnutých návrzích.

### 3.2 Sokratovské posouzení (krok 3a)

„/socratic skills“ ze zadání se v API nedá zavolat jako skill. Metoda je zabudovaná do promptu
`prompty/posouzeni.md`, který jde upravit. U každého návrhu Claude odpoví:

1. **Opora** – opírá se návrh o poptávku nebo podklady? (citace, nebo „žádná“)
2. **Předpoklad** – na jakém předpokladu stojí a je oprávněný? (např. „hodnotitel předpokládá, že
   klient chce pevnou cenu“)
3. **Důsledek** – co změna způsobí ve zbytku dokumentu? Nerozbije konzistenci (cena ↔ pracnost ↔
   harmonogram), nepřidá vymyšlený fakt, nenafoukne rozsah?

Pak rozhodne `prijato` / `castecne` / `odmitnuto`, zdůvodní to a u přijatých popíše, jak změnu
zapracuje. Návrh, který by vyžadoval vymyšlený fakt, se přijme jen jako `[DOPLNIT: …]`.

Neprobíhá žádný dialog s uživatelem. Hodnotitel ale v dalším kole vidí seznam dříve odmítnutých
návrhů s důvody a může návrh zopakovat jen s novým argumentem. Tím se omezí opakované přetahování
o tutéž věc.

### 3.3 Řízení smyčky

```
krok 0 → krok 1 (v1)
k = 1
opakuj:
    hodnocení k (verze vk)
    pokud cíl splněn               → konec „cíl splněn“
    pokud k = 4 (závěrečné)        → konec „vyčerpán limit 3 revizí“
    posouzení k
    pokud nic nepřijato            → konec „žádná přijatá změna“ (další hodnocení by hodnotilo totéž)
    zapracování k → v(k+1)
    k = k + 1
finální = verze s nejvyšším skóre
```

Limit revizí (3) a cílové skóre (9,5) jsou v `nastaveni.yaml`.

## 4. Hodnocení a skóre

### 4.1 Tři skupiny kritérií

| Skupina | Odkud | Výchozí váha |
|---|---|---|
| A – Povinné náležitosti | Krok 0, z konkrétní poptávky (u NRB 9× „musí obsahovat“ + 5× „žádáme o zaslání“ + rozsah plnění; po sloučení duplicit, např. harmonogram, zhruba 12–15 položek) | 50 % |
| B – Obecná kvalita | Profil dokumentu `profily/nabidka.yaml` | 35 % |
| C – Fakta | Pevné kritérium | 15 % |

Návrh obecných kritérií pro nabídku (váhy uvnitř skupiny B, upravitelné v YAML):

- **Konkrétnost** – konkrétní návrh realizace, ne obecné ujištění o schopnostech (výslovný požadavek
  poptávky). 25 %.
- **Ověřitelnost výstupů** – každá etapa má výstup a kritérium převzetí. 20 %.
- **Vnitřní konzistence** – cena = pracnost × sazba, harmonogram odpovídá etapám, odkazy na kapitoly
  sedí. 20 %.
- **Srozumitelnost pro zadavatele** – struktura, manažerské shrnutí, dohledatelnost požadavků (např.
  tabulka „požadavek → kde v nabídce“). 15 %.
- **Hranice a rizika** – předpoklady, omezení, co plnění není. 10 %.
- **Jazyk a forma** – spisovná čeština, profesní tón, přiměřený rozsah. 10 %.

### 4.2 Fakta a placeholdery

Obsah dokumentu má tři druhy. Hodnotitel i pisatel je dostanou v promptu výslovně rozlišené:

| Druh | Příklad | Pravidlo |
|---|---|---|
| Fakt ze zdrojů | rozsah do 20 osob (poptávka), sazba 15 000 Kč/MD (profil firmy) | smí se použít |
| Návrh dodavatele | pracnost etap v MD, délka workshopu, harmonogram, scénář, kritéria převzetí | smí se navrhnout – je to obsah nabídky, ne fakt |
| Neznámý fakt | cena bez sazby v profilu, IČ, jména, reference, certifikace, datum platnosti | jen `[DOPLNIT: co a proč]` |

- **Vymyšlený fakt** = konkrétní údaj třetího druhu, který není ve zdrojích (poptávka, `podklady/`).
  Hodnotitel ho vrací v seznamu `vymyslena_fakta` s citací. Skóre skupiny C počítá kód:
  10 při nule, jinak `max(1, 10 − 3 × počet)`.
- **Líný placeholder** = `[DOPLNIT]` tam, kde fakt ve zdrojích je, nebo kde jde o návrh, který měl
  dodavatel udělat. Penalizuje se ve skupině B (konkrétnost), ne jako vymyšlený fakt.
- **Odkazy na předpisy** (DORA, GDPR, čísla článků a lhůty) nejsou fakta o dodavateli a jsou dovolené.
  Riziko halucinace citací je ale reálné: reference je jich plná a chybné číslo článku by v nabídce
  bance škodilo. Hodnotitel proto podezřelé citace vypíše do `tvrzeni_k_overeni`. Do skóre nevstupují,
  v přehledu jsou jako samostatný kontrolní seznam pro konzultanta.
- **Deterministická kontrola v kódu** (`fakta.py`): najde částky v Kč, osmimístná čísla (IČ),
  e-maily, telefony, jména s tituly a URL, které se nevyskytují ve zdrojích, a vypíše je v přehledu
  jako „k ověření“. Do skóre nevstupují; jde o pojistku, kdyby je hodnotitel přehlédl.
- Krok 0 ověřuje v kódu, že každá citace náležitosti se v poptávce opravdu vyskytuje. Model si tak
  nemůže vymyslet požadavek.

### 4.3 Výpočet skóre a splnění cíle

```
A = průměr skóre položek N1…Nn
B = vážený průměr obecných kritérií
C = z počtu vymyšlených faktů (viz výše)
celkem = 0,50·A + 0,35·B + 0,15·C        (zaokrouhleno na 0,1)

cíl splněn ⇔ celkem ≥ 9,5
            ∧ žádná povinná náležitost < 8
            ∧ žádný vymyšlený fakt
```

Pojistky (minimum u náležitostí, nula vymyšlených faktů) brání tomu, aby vysoký průměr zakryl
chybějící povinnou část nebo vymyšlenou referenci. Prahy jsou v `nastaveni.yaml`.

### 4.4 Výstup hodnotitele (JSON)

Vynucený přes OpenAI Structured Outputs (`strict: true`) a v kódu znovu validovaný Pydantic modelem:

```json
{
  "kriteria": [
    {"id": "N3", "skore": 7, "zduvodneni": "…", "dukaz": "citace z dokumentu nebo 'chybí'"}
  ],
  "vymyslena_fakta": [{"citace": "…", "proc": "není v poptávce ani v podkladech"}],
  "tvrzeni_k_overeni": [{"citace": "…", "proc": "…"}],
  "navrhy": [
    {"id": "H1-03", "kriterium": "N3", "misto": "kap. 8", "problem": "…",
     "navrh": "konkrétní nové znění nebo úprava", "priorita": "vysoka|stredni|nizka"}
  ],
  "celkovy_komentar": "…"
}
```

Kód kontroluje: každé kritérium ze vstupu má právě jedno skóre, skóre je 1–10 (krok 0,5), ID návrhů
jsou unikátní, počet návrhů je nejvýše `max_navrhu` (výchozí 10, aby revize zůstala soustředěná).
Celkové skóre od modelu se nechce, počítá ho kód.

Hodnotitel nevidí předchozí skóre (aby se nekotvil). Vidí jen dříve odmítnuté návrhy s důvody (kap. 3.2).

## 5. Úprava kritérií a chování bez zásahu do kódu

```
nastaveni.yaml              modely, cílové skóre, limit revizí, váhy skupin, prahy, výchozí profil
profily/
  nabidka.yaml              obecná kritéria (název, popis pro hodnotitele, váha), pokyny ke struktuře
  smernice.yaml             zárodek pro interní směrnici (v prototypu nevyladěný)
prompty/
  nalezitosti.md  navrh.md  hodnoceni.md  posouzeni.md  zapracovani.md  porovnani.md
input/<název>.kriteria.yaml volitelně: kritéria navíc / změna vah jen pro tuto poptávku
podklady/                   volitelně: profil_firmy.md, šablona stylů sablona.docx
```

- Všechny YAML soubory jsou česky komentované. Při startu se validují; chyba ohlásí soubor, řádek
  a co je špatně („Váha kritéria ‚Konkrétnost‘ musí být číslo, je ‚vysoká‘.“).
- Kopie použité konfigurace a promptů se uloží do složky běhu. Každý běh je pak reprodukovatelný
  a porovnatelný i po úpravě kritérií.
- Je-li v `profily/` víc profilů, nástroj se po výběru souboru zeptá „Nabídka, nebo směrnice?“.
  Při jednom profilu se neptá.
- `podklady/` se přidá do `.gitignore` (profil firmy obsahuje osobní údaje). Do repa půjde
  `podklady.priklad/profil_firmy.md` jako vyplnitelná šablona: sazba, tým (role, praxe), reference,
  identifikační údaje, standardní obchodní podmínky.

## 6. Volání modelů

| Krok | Model | Výstup | Poznámka |
|---|---|---|---|
| 0 | Claude | JSON (structured outputs, `messages.parse`) | effort `medium` |
| 1, 3b | Claude | čistý Markdown | streaming (dlouhý výstup), `max_tokens` 64 000, effort `high` |
| 3a | Claude | JSON | effort `high` |
| 2 | GPT | JSON (Responses API, `text.format` json_schema, `strict`) | reasoning effort `high` |
| porovnání | GPT | JSON | kap. 11 |

- Dokument se v kroku 3b vrací jako čistý text, ne jako pole v JSON. Escapování 15 000 tokenů textu
  v JSON je zbytečné riziko. Kód kontroluje, že výstup nebyl uříznutý (`stop_reason`), že nezmizely
  nadpisy první úrovně a že se dokument nezkrátil o víc než 30 % bez přijatého návrhu na zkrácení.
  Při porušení následuje jeden opakovaný pokus, pak srozumitelná chyba.
- Zdroje (poptávka, profil firmy, kritéria) tvoří stabilní začátek promptu u všech volání Claude
  a cachují se (prompt caching). Levnější a rychlejší opakovaná volání.
- U `claude-opus-5-5` je zapnutá serverová záloha při odmítnutí (`fallbacks: "default"`) a kód
  ošetřuje `stop_reason == "refusal"`.
- **Ověřit při implementaci** (v dokumentaci se nepodařilo dohledat přesně): tvar parametru reasoning
  effort v Responses API pro `gpt-6-astra` a omezení JSON Schema ve strict režimu.

Ověřené verze (PyPI, 2026-10-17): `anthropic` 1.15.0, `openai` 3.33.0, `pydantic` 2.14.1,
`python-dotenv` 1.2.4, `pyyaml` 6.0.3, `pypandoc-binary` 1.17 (má Windows wheel s přibaleným
pandocem, konzultant nic dalšího neinstaluje). Navíc `jinja2` pro HTML přehled, `pytest` pro testy.
Verze se v `requirements.txt` pinují přesně. Python ≥ 3.10, lokálně je 3.12.4.

Odhad nákladů jednoho plného běhu (12 volání, dokument kolem 15 000 tokenů): zhruba 3–6 USD,
15–30 minut. Odhad není změřený; skutečnou spotřebu tokenů a cenu zapisuje každý běh do přehledu.

## 7. Výstup – co uživatel uvidí

```
output/2026-10-17_1432_narodni-rozvojova-banka/
  prehled.html                    ← začít tady
  FINALNI_nabidka.docx
  FINALNI_nabidka.md
  01_poptavka.md                  vstup převedený do Markdownu (co modely skutečně viděly)
  02_nalezitosti.md
  03_navrh_v1.md
  04_hodnoceni_1.md               skóre po kritériích, vymyšlená fakta, návrhy
  05_posouzeni_1.md               každý návrh: opora / předpoklad / důsledek → rozhodnutí + důvod
  06_navrh_v2.md
  06_navrh_v2_zmeny.html          barevný rozdíl proti v1
  07_hodnoceni_2.md
  …
  data/                           strojová data: *.json k hodnocení a posouzení, beh.json,
                                  kopie konfigurace a promptů, beh.log
```

- Název složky: datum, čas (aby se dva běhy téhož dne nepřepsaly) a název vstupu bez diakritiky.
  Diakritika v cestách dělala potíže v konzoli Windows už při průzkumu dat.
- Čísla souborů odpovídají pořadí vzniku. Lidsky čitelné soubory jsou nahoře, JSON v `data/`.
- **Přehled změn** k revizi: diff spočítá kód (`difflib`), takže je pravdivý, ne převyprávěný
  modelem. Posouzení k němu přidává lidský popis, co a proč se měnilo.
- **`prehled.html`** (statický soubor bez JavaScriptu, otevře se dvojklikem):
  1. výsledek: důvod ukončení, finální skóre, odkaz na finální dokument, a když finální není poslední
     verze, proč;
  2. tabulka skóre: kritéria × hodnocení 1–4, barevně, se skupinami A/B/C a celkem;
  3. **Co musíte doplnit**: všechny `[DOPLNIT: …]` z finálního dokumentu;
  4. **K ověření**: tvrzení o předpisech a podezřelé údaje z kontroly v kódu;
  5. časová osa kroků s odkazy na soubory, statistika návrhů (přijato / částečně / odmítnuto);
  6. modely, spotřeba tokenů a cena, doba běhu.

Finální DOCX se generuje pandocem. Je-li v `podklady/` soubor `sablona.docx`, použijí se jeho styly
(`--reference-doc`), takže lze převzít vzhled firemních nabídek.

## 8. Ovládání

- **První spuštění:** `spustit.bat` vytvoří `.venv`, nainstaluje závislosti, zkontroluje `.env`
  (chybí-li klíč, řekne který a kde ho doplnit; vzor je v `.env.example`) a spustí běh.
- **Běh:** jeden soubor v `input/` → spustí se rovnou. Víc souborů → očíslovaný výběr v konzoli.
- **Průběh** v konzoli česky, krok po kroku: `[4/12] Hodnocení 1 (GPT)… hotovo, skóre 7,8`.
- Na konci okno nezmizí (`pause`) a vypíše cestu k přehledu. Volitelně ho rovnou otevře.
- Další příkazy pro vývoj a ladění (také jako `.bat`):
  - `python -m refiner --pokracovat <složka běhu>` – dokončí přerušený běh od posledního hotového kroku;
  - `python -m refiner --nanecisto` – celý běh s falešnými modely, bez API a bez nákladů (ukázka
    struktury výstupu, test instalace);
  - `python -m refiner porovnat <složka běhu>` – porovnání s referencí (kap. 11).

## 9. Chyby a odolnost

- Po každém kroku se výstup okamžitě zapíše na disk a stav uloží do `data/beh.json`. Pád v kroku
  k neztratí kroky 1…k−1.
- Přechodné chyby (síť, timeout, 429, 5xx) opakuje SDK (`max_retries` v konfiguraci, výchozí 4).
  Teprve když ani to nepomůže, běh se zastaví.
- Při zastavení se: zapíše stav `prerusen` s důvodem, vygeneruje `prehled.html` z toho, co existuje
  (s červeným blokem „Běh byl přerušen“), vypíše česká hláška s doporučeným dalším krokem a program
  skončí nenulovým kódem. Žádná chyba neskončí potichu.

| Situace | Hláška (zkráceně) |
|---|---|
| chybí / neplatný klíč (401) | „Klíč OPENAI_API_KEY v souboru .env chybí nebo je neplatný.“ |
| vyčerpaný kredit vs. rate limit (429) | rozliší se podle typu chyby: „Došel kredit u OpenAI“ / „Služba je přetížená, zkuste to za pár minut a použijte --pokracovat.“ |
| timeout / síť | „Nepodařilo se spojit se službou Anthropic. Zkontrolujte připojení a použijte --pokracovat.“ |
| nevalidní JSON / chybějící kritérium | jeden pokus o opravu (modelu se pošle chybový popis); pak hláška a surová odpověď v `data/` |
| uříznutý výstup | jeden opakovaný pokus; pak hláška |
| odmítnutí modelem | hláška s kategorií odmítnutí |
| chyba konfigurace | před prvním voláním API, se souborem a řádkem |

Technický detail (traceback) jde do `data/beh.log`, ne do konzole.

## 10. Architektura

```
refiner/
  __main__.py      CLI (běh, --pokracovat, --nanecisto, porovnat), výběr souboru, konzolové hlášky
  konfigurace.py   načtení a validace YAML (Pydantic), sloučení s kritérii k poptávce
  vstup.py         DOCX/MD/TXT → Markdown (pandoc)
  modely/
    rozhrani.py    protokoly Pisatel / Hodnotitel (to, co smyčka potřebuje)
    claude.py      Anthropic SDK
    gpt.py         OpenAI SDK
    falesne.py     skriptované odpovědi pro testy a --nanecisto
    chyby.py       převod výjimek obou SDK na jednotnou ChybaModelu s českou hláškou
  kroky.py         sestavení promptů z prompty/*.md, volání, validace výstupů
  skore.py         čisté funkce: výpočet A/B/C, celkem, splnění cíle
  fakta.py         deterministická kontrola údajů, sběr placeholderů
  smycka.py        orchestrace podle kap. 3.3; dostane modely a úložiště zvenku
  beh.py           složka běhu, číslování, beh.json, obnovení
  vystup/          Markdown hodnocení a posouzení, HTML diff, prehled.html (Jinja2), DOCX export
  porovnani.py     kap. 11
prompty/  profily/  nastaveni.yaml  podklady.priklad/  tests/
spustit.bat  pokracovat.bat  porovnat.bat  requirements.txt  .env.example  README.md
```

Smyčka nezná konkrétní SDK, pracuje jen s rozhraním. Díky tomu jdou testy i režim `--nanecisto`
nad falešnými modely a výměna modelu je změna konfigurace.

## 11. Porovnání s referencí

Referenční nabídka se **nikdy nepředává pisateli** (generování nečte `examples/`). Jinak by
porovnání nic neměřilo.

Příkaz `porovnat` vytvoří ve složce běhu `porovnani.html` ze čtyř částí:

1. **Kalibrace hodnotitele** – reference projde stejným hodnocením (stejné náležitosti, kritéria,
   profil firmy). Když ručně dotažená nabídka dostane např. 8,7, víme, že práh 9,5 je pro tohoto
   hodnotitele nereálný nebo že kritéria měří něco jiného, než chceme. Jedno volání GPT, výsledek
   nejcennější ze všech.
2. **Párové srovnání po kritériích** – GPT u každého kritéria určí, který dokument je lepší a proč.
   Dokumenty jsou anonymizované jako A/B a porovnání proběhne dvakrát s prohozeným pořadím; při
   rozporu se výsledek označí jako „nerozhodně“. Tím se omezí zkreslení pořadím.
3. **Pokrytí obsahu** – z reference se vytáhne seznam konkrétních prvků (např. závazný cenový strop,
   kritéria převzetí po etapách, matice pokrytí cílů, stavové zprávy po milnících, definice vady)
   a ke každému se určí: v generované nabídce je / částečně / chybí. Seznam chybějících prvků je
   přímý podnět pro úpravu promptů a profilu.
4. **Lidské hodnocení** – krátký formulář pro konzultanta v přehledu: Odeslal bych to po doplnění
   placeholderů? Kolik minut práce do odeslatelné verze? Věcné chyby? Co chybí? Co je lepší než
   v referenci? Tohle je skutečné měřítko úspěchu, automatické části slouží k ladění.

Pro férové srovnání je potřeba vyplnit `podklady/profil_firmy.md` stejnými fakty, jaké má reference
(sazba, tým, reference). Jinak bude generovaná nabídka v kapitolách cena/tým/reference
z definice horší.

## 12. Testy

`pytest`, bez sítě. Autouse fixture zablokuje sockety a smaže klíče z prostředí, takže omylem
spuštěné skutečné volání test shodí, místo aby stálo peníze.

- **Parsování hodnocení:** validní JSON; chybějící kritérium; skóre mimo rozsah; duplicitní ID;
  nevalidní JSON → pokus o opravu → úspěch / selhání.
- **Výpočet skóre:** váhy skupin a kritérií, zaokrouhlení, pojistky (náležitost < 8, vymyšlený fakt
  blokuje cíl i při průměru 9,8), skóre C z počtu faktů.
- **Ukončení smyčky:** cíl splněn v 1. a ve 2. hodnocení; 3 revize + závěrečné hodnocení (přesně
  4 hodnocení, 3 revize); nic nepřijato → konec bez dalšího hodnocení; skóre po revizi kleslo →
  finální je dřívější verze.
- **Chyby API:** výjimka z falešného modelu v různých krocích → stav `prerusen`, dřívější soubory
  zůstaly, přehled vygenerován, česká hláška; `--pokracovat` naváže a hotové kroky nevolá znovu.
- **Mapování výjimek:** reálné výjimkové třídy obou SDK (`RateLimitError`, `APITimeoutError`,
  `APIConnectionError`, `AuthenticationError` …) sestavené v testu → správná hláška.
- **Ostatní:** číslování souborů, název složky bez diakritiky, citace náležitostí ověřené proti
  poptávce, kontrola údajů v `fakta.py`, sběr placeholderů, validace konfigurace, převod
  DOCX → MD na malém testovacím DOCX (vytvořeném v testu, ne z `input/`).

## 13. Anonymizace – rozhodnutí

Prototyp posílá poptávku a profil firmy oběma API bez úprav.

- Data z API se podle podmínek obou poskytovatelů standardně nepoužívají k trénování. Nastavení
  organizace (retence) je ale potřeba ověřit v konzolích obou účtů.
- Poptávka obvykle není důvěrná. Profil firmy obsahuje osobní údaje členů týmu.
- **Pozor na souvislost:** referenční nabídka sama klientovi slibuje, že s jeho podklady budou
  pracovat jen nástroje, které klient písemně schválí, a jen v anonymizované podobě. Pro poptávku
  to nevadí, ale nástroj se nesmí používat na neveřejné podklady klienta (jeho předpisy, smlouvy)
  bez takového schválení. README to uvede výslovně.
- Možné rozšíření později: tabulka náhrad (`NRB` → `[KLIENT]`) aplikovaná před odesláním a vrácená
  ve finálním dokumentu. Je to malé a deterministické, ale v prototypu to není.

## 14. Mimo scope

GUI, více uživatelů, paralelní běhy, automatická anonymizace, vstup PDF, vyladěný profil směrnice,
generování příloh (XLSX apod.), práce s obrázky v DOCX.

## 15. Rizika a otevřené body

- **Šum hodnotitele:** stejný dokument může dostat skóre lišící se o ±0,5. Práh 9,5 se možná
  nebude dosahovat vůbec a smyčka poběží vždy na limit. To je přijatelné; kalibrace na referenci
  (kap. 11) ukáže, zda práh upravit.
- **Drift při přepisu:** Claude může při zapracování změnit i to, co neměl. Brání tomu instrukce
  v promptu a pravdivý diff; hodnotitel posuzuje vždy celý dokument.
- **Délka:** reference má kolem 45 kB a 14 tabulek. Model může psát kratší a obecnější text.
  Kritérium „konkrétnost“ a pokyny ke struktuře v profilu na to míří; porovnání ukáže, zda stačí.
- **Tabulky:** Markdown tabulky se do DOCX převádějí dobře, ale vzhled bude prostší než u reference.
  Šablona stylů pomůže jen částečně.
- **Citace předpisů:** halucinace čísel článků se nedá v prototypu automaticky vyloučit, jen
  zviditelnit (kap. 4.2).

## 16. Navržené fáze implementace (detail v samostatném plánu)

1. Kostra projektu, konfigurace a validace, převod vstupu, `.bat`, `.env.example`.
2. Rozhraní modelů, falešné modely, `skore.py`, `smycka.py`, `beh.py` – vše testované bez API.
3. Skutečné klienty Claude a GPT, mapování chyb, prompty.
4. Výstupy: Markdown soubory, diffy, `prehled.html`, DOCX export.
5. První ostrý běh na poptávce NRB, `porovnat`, ladění promptů a kritérií podle výsledků.

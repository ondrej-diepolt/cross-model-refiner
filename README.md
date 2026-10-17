# cross-model-refiner

Nástroj napíše odpověď na poptávku (nabídku) a postupně ji vylepšuje: **Claude** dokument píše,
**GPT** ho nezávisle hodnotí podle kritérií a navrhuje úpravy, Claude návrhy posoudí a přijaté
zapracuje. Smyčka končí, když dokument dosáhne cílového skóre, nebo po nastaveném počtu revizí.
Výsledkem je hotový dokument (DOCX a Markdown) a přehled celého běhu v prohlížeči.

## Data a důvěrnost – přečtěte před prvním použitím

- Nástroj posílá **poptávku a profil firmy** (`podklady/`) službám **Anthropic a OpenAI bez
  jakýchkoli úprav**. Žádná anonymizace neprobíhá.
- Data z API se podle podmínek obou poskytovatelů standardně nepoužívají k trénování. Nastavení
  organizace (doba uchovávání dat) je ale potřeba ověřit v konzolích obou účtů.
- Poptávka obvykle není důvěrná. Profil firmy obsahuje osobní údaje členů týmu.
- **Nástroj se nesmí používat na neveřejné podklady klienta** (jeho předpisy, smlouvy, interní
  dokumenty) bez jeho písemného souhlasu. Naše nabídky klientům slibují, že s jejich podklady budou
  pracovat jen nástroje, které klient písemně schválí, a jen v anonymizované podobě.

## První spuštění

1. Nainstalujte **Python 3.10 nebo novější** z [python.org](https://www.python.org/downloads/).
   Při instalaci zaškrtněte **„Add python.exe to PATH“**.
2. Zkopírujte soubor `.env.example` jako `.env` a doplňte do něj oba API klíče
   (`ANTHROPIC_API_KEY` a `OPENAI_API_KEY`; kde je získat, je napsáno přímo v souboru).
   Soubor `.env` nikomu neposílejte a neukládejte do gitu.
3. Dvakrát klikněte na `spustit.bat`. Poprvé si nástroj vytvoří prostředí `.venv` a nainstaluje
   knihovny (několik minut, potřebuje internet). Další spuštění už jsou rychlá.

Chybí-li klíč, nástroj řekne který a skončí dřív, než cokoli odešle.

## Běžné použití

1. Vložte poptávku (DOCX, MD nebo TXT) do složky `input/`.
2. Dvakrát klikněte na `spustit.bat`.
   - Je-li v `input/` víc souborů, vyberete číslem, kterou poptávku zpracovat.
   - Nástroj se zeptá „Nabídka, nebo směrnice?“ (profil dokumentu; směrnice je zatím jen zárodek).
3. V konzoli uvidíte průběh krok po kroku, např. `[3/12] Hodnocení 1… hotovo, skóre 7,9`.
4. Na konci se v prohlížeči otevře **`prehled.html`** – začněte tam. Najdete v něm finální skóre,
   tabulku hodnocení, seznam **Co musíte doplnit** (všechna místa `[DOPLNIT: …]`) a **K ověření**
   (citace předpisů a podezřelé údaje).

Výsledky jsou ve složce `output/<datum_čas_název-poptávky>/`:

| Soubor | Obsah |
|---|---|
| `prehled.html` | přehled běhu – začněte tady |
| `FINALNI_nabidka.docx`, `FINALNI_nabidka.md` | finální dokument (verze s nejvyšším skóre); u profilu směrnice `FINALNI_smernice.*` – obecně `FINALNI_<profil>.*` |
| `01_poptavka.md` | poptávka převedená do textu – co modely skutečně viděly |
| `02_nalezitosti.md` | povinné náležitosti vytažené z poptávky |
| `03_navrh_v1.md`, `06_navrh_v2.md`… | jednotlivé verze dokumentu |
| `04_hodnoceni_1.md`… | skóre po kritériích, vymyšlená fakta, návrhy úprav |
| `05_posouzeni_1.md`… | jak Claude posoudil každý návrh a proč ho přijal či odmítl |
| `*_zmeny.html` | barevný rozdíl proti předchozí verzi |
| `data/` | strojová data, kopie použité konfigurace a promptů, technický log `beh.log` |

Finální dokument **vždy zkontrolujte** a doplňte místa `[DOPLNIT: …]` – jsou to údaje, které
nástroj nezná (a proto si je nevymýšlí).

## Profil firmy

Nástroj zná o vaší firmě jen to, co mu dáte do složky `podklady/` (do gitu se neukládá):

- `podklady/profil_firmy.md` – zkopírujte šablonu `podklady.priklad/profil_firmy.md` a vyplňte
  identifikaci, sazby, tým, reference a obchodní podmínky. Bez sazby nástroj nespočítá cenu.
- `podklady/sablona.docx` (volitelně) – Word dokument, jehož styly (písma, nadpisy, barvy) se
  použijí pro finální DOCX. Stačí uložit některou firemní nabídku jako `sablona.docx`.

Všechny další soubory DOCX, MD a TXT v `podklady/` se také předají modelům jako podklady.

## Úprava kritérií a chování

Vše se mění v textových souborech, bez zásahu do kódu. Soubory se kontrolují při startu; chyba
ohlásí soubor, řádek a co je špatně.

- `nastaveni.yaml` – modely, cílové skóre (výchozí 9,5), maximální počet revizí, váhy skupin
  kritérií, ceny tokenů.
- `profily/*.yaml` – profil dokumentu: obecná kritéria kvality (název, popis pro hodnotitele, váha)
  a doporučená struktura dokumentu.
- `input/<název poptávky>.kriteria.yaml` (volitelně) – kritéria navíc nebo jiné váhy jen pro jednu
  poptávku. Příklad pro poptávku `input/banka.docx` → soubor `input/banka.kriteria.yaml`:

  ```yaml
  kriteria_navic:
    - id: X1
      nazev: Regulatorní soulad
      popis: Nabídka konkrétně řeší požadavky DORA.
      vaha: 0.2
  vahy: {B1: 0.3}
  ```

- `prompty/*.md` – pokyny pro modely v jednotlivých krocích. Proměnné `${...}` doplňuje nástroj;
  znak `$` v běžném textu pište jako `$$`.

Každý běh si do `data/konfigurace/` uloží **kopii** použitého nastavení, profilu a promptů.

## Přerušený běh

Když běh skončí chybou (výpadek internetu, došlý kredit, přetížená služba…), nástroj vypíše česky,
co se stalo, uloží rozpracovaný běh a vytvoří přehled s tím, co už je hotové. Po odstranění příčiny
dvakrát klikněte na **`pokracovat.bat`** – naváže na posledním přerušeném běhu a hotové kroky už
neplatí znovu. Konkrétní běh lze dokončit přetažením jeho složky z `output/` na `pokracovat.bat`.

Pozor: pokračující běh používá **kopii konfigurace a promptů uloženou ve složce běhu**
(`data/konfigurace/`). Úprava `prompty/`, `profily/` nebo `nastaveni.yaml` v repozitáři se na
pokračování už rozběhnutého běhu neprojeví – platí jen pro nové běhy.

## Ukázka bez nákladů

```
spustit.bat --nanecisto
```

(v příkazovém řádku ve složce nástroje). Projde celý běh s falešnými modely – bez volání API, bez
klíčů a zdarma. Výstup má stejnou strukturu jako ostrý běh, texty jsou jen ukázkové. Hodí se pro
ověření instalace a seznámení s výstupy.

## Kolik to stojí

Orientačně **3–6 USD a 15–30 minut** za jeden plný běh (asi 12 volání modelů, dokument kolem
15 000 tokenů). Odhad není změřený; skutečnou spotřebu tokenů a cenu každého běhu najdete
v `prehled.html`.

## Pro vývojáře

```
.venv\Scripts\python.exe -m refiner [--nanecisto]
.venv\Scripts\python.exe -m refiner --pokracovat [SLOZKA_BEHU]
.venv\Scripts\python.exe -m pytest
```

Návratové kódy: 0 hotovo, 1 běh přerušen (lze pokračovat), 2 chyba konfigurace, vstupu nebo
chybějící klíč. Testy nevolají síť ani API.

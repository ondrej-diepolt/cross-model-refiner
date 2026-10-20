# cross-model-refiner

Nástroj napíše odpověď na poptávku (nabídku) a postupně ji vylepšuje: **Claude** dokument píše,
**GPT** ho nezávisle hodnotí podle kritérií a navrhuje úpravy, Claude návrhy posoudí a přijaté
zapracuje. Smyčka končí, když dokument dosáhne cílového skóre, nebo po nastaveném počtu revizí.
Výsledkem je hotový dokument (DOCX a Markdown) a přehled celého běhu v prohlížeči.

## Data a důvěrnost – přečtěte před prvním použitím

- Nástroj posílá **poptávku a profil firmy** (`materials/`) službám **Anthropic a OpenAI bez
  jakýchkoli úprav**. Žádná anonymizace neprobíhá.
- Data z API se podle podmínek obou poskytovatelů standardně nepoužívají k trénování. Nastavení
  organizace (doba uchovávání dat) je ale potřeba ověřit v konzolích obou účtů.
- **Ve výchozím režimu předplatného** (viz níže) data neodcházejí přes API, ale přes přihlášené
  nástroje Claude Code a Codex. Platí pro ně podmínky a nastavení soukromí vašich předplatných
  (Claude Max, ChatGPT), které se od podmínek API mohou lišit – ověřte je v nastavení obou účtů.
- Poptávka obvykle není důvěrná. Profil firmy obsahuje osobní údaje členů týmu.
- Příkaz **`compare`** (`compare.bat`) posílá službě **OpenAI navíc celou referenční nabídku**
  z `examples/` – včetně jmen členů týmu, cen a referencí – spolu s generovanou nabídkou
  a poptávkou.
- **Nástroj se nesmí používat na neveřejné podklady klienta** (jeho předpisy, smlouvy, interní
  dokumenty) bez jeho písemného souhlasu. Naše nabídky klientům slibují, že s jejich podklady budou
  pracovat jen nástroje, které klient písemně schválí, a jen v anonymizované podobě.

## První spuštění

1. Nainstalujte **Python 3.10 nebo novější** z [python.org](https://www.python.org/downloads/).
   Při instalaci zaškrtněte **„Add python.exe to PATH“**.
2. Výchozí režim je **předplatné** (`models.mode: subscription` v `settings.yaml`) a soubor `.env`
   ani API klíče nepotřebuje. Nainstalujte a přihlaste oba nástroje:
   - **Claude Code**: nainstalujte ho a v příkazovém řádku spusťte `claude`, v něm `/login`
     a přihlaste se účtem s předplatným **Max**.
   - **Codex CLI**: nainstalujte ho a spusťte `codex login`, přihlaste se účtem **ChatGPT**.

   Přihlášení ověříte příkazy `claude auth status` (musí být `authMethod: claude.ai`)
   a `codex login status` (musí být „Logged in using ChatGPT“). Chybí-li nástroj nebo přihlášení,
   nástroj to česky řekne a skončí dřív, než cokoli odešle. Volání čerpají z limitu předplatného;
   když se vyčerpá, běh se přeruší a po obnovení limitu ho dokončí `resume.bat`.
3. Dvakrát klikněte na `run.bat`. Poprvé si nástroj vytvoří prostředí `.venv` a nainstaluje
   knihovny (několik minut, potřebuje internet). Další spuštění už jsou rychlá.

**Klíče z `.env` se v režimu předplatného do nástrojů nikdy nepředávají** – proměnné s API klíči
a přihlašovacími tokeny se podprocesům odstraní, aby se omylem neúčtovalo přes API.

### Režim API (volitelný)

Chcete-li místo předplatného platit přes API, nastavte v `settings.yaml` `models.mode: api`
a zkopírujte soubor `.env.example` jako `.env`. Doplňte do něj oba API klíče
(`ANTHROPIC_API_KEY` a `OPENAI_API_KEY`; kde je získat, je napsáno přímo v souboru).
Soubor `.env` nikomu neposílejte a neukládejte do gitu. Chybí-li klíč, nástroj řekne který
a skončí dřív, než cokoli odešle. V tomto režimu platí oddíly `claude` a `gpt` v `settings.yaml`
a přehled uvádí odhad ceny v USD.

## Běžné použití

1. Vložte poptávku (DOCX, MD nebo TXT) do složky `input/`.
2. Dvakrát klikněte na `run.bat`.
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
| `FINALNI_nabidka.docx`, `FINALNI_nabidka.md` | finální dokument (verze, která splnila cíl; když žádná, verze s nejvyšším skóre); u profilu směrnice `FINALNI_smernice.*` – obecně `FINALNI_<profil>.*` |
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

Nástroj zná o vaší firmě jen to, co mu dáte do složky `materials/` (do gitu se neukládá):

- `materials/company_profile.md` – zkopírujte šablonu `materials.example/company_profile.md` a vyplňte
  identifikaci, sazby, tým, reference a obchodní podmínky. Bez sazby nástroj nespočítá cenu.
- `materials/template.docx` (volitelně) – Word dokument, jehož styly (písma, nadpisy, barvy) se
  použijí pro finální DOCX. Stačí uložit některou firemní nabídku jako `template.docx`.

Všechny další soubory DOCX, MD a TXT v `materials/` se také předají modelům jako podklady.

Existuje-li `materials/`, použije se tato složka. Jinak se načte starší složka `podklady/`;
jejich obsah se neslučuje. Pro DOCX má přednost `template.docx`, jinak `sablona.docx`.
Oba názvy šablony se vynechávají z textových podkladů posílaných modelům.


## Úprava kritérií a chování

Vše se mění v textových souborech, bez zásahu do kódu. Soubory se kontrolují při startu; chyba
ohlásí soubor, řádek a co je špatně.

- `settings.yaml` – modely, cílové skóre (výchozí 9,5), maximální počet revizí, váhy skupin
  kritérií, ceny tokenů.
- `profiles/*.yaml` – profil dokumentu: obecná kritéria kvality (název, popis pro hodnotitele, váha)
  a doporučená struktura dokumentu.
- `input/<název poptávky>.criteria.yaml` (volitelně) – kritéria navíc nebo jiné váhy jen pro jednu
  poptávku. Příklad pro poptávku `input/banka.docx` → soubor `input/banka.criteria.yaml`:

  ```yaml
  extra_criteria:
    - id: X1
      name: Regulatorní soulad
      description: Nabídka konkrétně řeší požadavky DORA.
      weight: 0.2
  weights: {B1: 0.3}
  ```

Má-li poptávka současně soubory `.criteria.yaml` a starší `.kriteria.yaml`, použije se
jen `.criteria.yaml`. Starší české klíče konfigurace se dál načítají; nové příklady používají
anglické klíče. Vestavěné profily jsou `profiles/proposal.yaml` (nabídka) a
`profiles/policy.yaml` (směrnice), ale výstupy dál nesou názvy `FINALNI_nabidka.*` a
`FINALNI_smernice.*`.

- `prompts/*.md` – pokyny pro modely v jednotlivých krocích. Proměnné `${...}` doplňuje nástroj;
  znak `$` v běžném textu pište jako `$$`.

Každý běh si do `data/konfigurace/` uloží **kopii** použitého nastavení, profilu a promptů.

## Přerušený běh

Když běh skončí chybou (výpadek internetu, došlý kredit, přetížená služba…), nástroj vypíše česky,
co se stalo, uloží rozpracovaný běh a vytvoří přehled s tím, co už je hotové. Po odstranění příčiny
dvakrát klikněte na **`resume.bat`** – naváže na posledním přerušeném běhu a hotové kroky už
neplatí znovu. Konkrétní běh lze dokončit přetažením jeho složky z `output/` na `resume.bat`.

Co pokračující běh použije:

- **Nastavení modelů** (oddíl `models:` – limity tokenů, časový limit, effort, názvy modelů)
  a ceny tokenů bere z **aktuálního `settings.yaml` v repozitáři**. Když běh skončí hláškou
  o uříznuté odpovědi nebo o vypršení času, upravte příslušnou hodnotu v `settings.yaml`
  (např. `max_tokens_json` nebo `max_output_tokens`, `timeout_s`) a spusťte `resume.bat`.
  Která nastavení se použila, je zapsáno v `data/beh.log`. Je-li `settings.yaml` v repozitáři
  chybný nebo chybí, běh pokračuje s kopií ve složce běhu a vypíše varování.
- Vše ostatní – cílové skóre a další řízení smyčky, váhy skupin, profil, kritéria a prompty – bere
  z **kopie uložené ve složce běhu** (`data/konfigurace/`), aby skóre zůstalo srovnatelné. Úprava
  `prompts/`, `profiles/` nebo těchto částí `settings.yaml` se projeví až v novém běhu.

Ukázkový běh (`--dry-run`) se dokončuje také s `--dry-run` (`resume.bat --dry-run`);
ostrý běh bez něj. `resume.bat` bez parametru vybírá jen běhy odpovídajícího druhu.

Po Ctrl+C se Windows zeptá „Terminate batch job (Y/N)?“ (česky „Ukončit dávkovou úlohu (A/N)?“).
Odpověď **N** nechá okno otevřené s hláškou, jak pokračovat; odpověď **Y** okno hned zavře
(přeskočí závěrečné „Pokračujte stisknutím libovolné klávesy“). Běh je uložený v obou případech.

## Porovnání s referencí

Porovná dokončený běh s ručně dotaženou referenční nabídkou. Slouží k ladění promptů a kritérií
a k ověření, že je výsledek reálně použitelný.

1. Vložte referenční nabídku (DOCX, MD nebo TXT) do složky `examples/` – **právě jeden soubor**.
   Generování nabídek složku `examples/` nikdy nečte; referenci uvidí jen hodnotitel (GPT)
   při porovnání. Porovnání volá jen hodnotitele GPT (v režimu předplatného Codex, v režimu API
   stačí klíč `OPENAI_API_KEY`).
2. Dvakrát klikněte na **`compare.bat`** – porovná poslední dokončený běh v `output/`. Konkrétní
   běh porovnáte přetažením jeho složky na `compare.bat`. Jiná reference:
   `compare.bat SLOZKA_BEHU --reference cesta\k\nabidce.docx`.
3. Ve složce běhu vznikne **`porovnani.html`** (otevře se v prohlížeči):
   - **Kalibrace hodnotitele** – reference projde stejným hodnocením jako generovaná nabídka.
     Když ani ručně dotažená nabídka nedosáhne cílového skóre, je práh pro tohoto hodnotitele
     nereálný, nebo kritéria měří něco jiného, než chceme.
   - **Párové srovnání po kritériích** – GPT porovná oba dokumenty anonymizované jako A/B dvakrát,
     s prohozeným pořadím; při rozporu je výsledek „nerozhodně“.
   - **Pokrytí obsahu** – konkrétní prvky reference a zda jsou v generované nabídce
     (chybějící první – přímý podnět pro úpravu promptů a profilu).
4. Vyplňte **`porovnani_formular.md`** (odeslal bych to? kolik minut práce do odeslatelné verze?
   věcné chyby? co chybí? co je lepší než v referenci?). To je skutečné měřítko úspěchu.

Porovnání stojí 5 volání GPT (spotřeba se připíše do `data/beh.json` běhu, stav běhu se nemění)
a dá se opakovat: výsledky se přepíšou, vyplněný formulář zůstane. Prompty porovnání
(`prompts/comparison_*.md`) a nastavení modelů (oddíl `models:` v `settings.yaml`) se berou vždy
aktuální z repozitáře; kalibrace hodnotí promptem uloženým v běhu, stejně jako generovanou
nabídku. Ukázkové běhy (`--dry-run`) porovnat nelze – mají jen falešné texty. Pro férové srovnání vyplňte
`materials/company_profile.md` stejnými fakty, jaké má reference (sazba, tým, reference) – jinak bude
generovaná nabídka v kapitolách cena, tým a reference z definice horší.

## Ukázka bez nákladů

```
run.bat --dry-run
```

(v příkazovém řádku ve složce nástroje). Projde celý běh s falešnými modely – bez volání API, bez
klíčů a zdarma. Výstup má stejnou strukturu jako ostrý běh, texty jsou jen ukázkové. Hodí se pro
ověření instalace a seznámení s výstupy. Běh je ve svém stavu označen jako ukázkový; pokračovat
v něm lze jen s `--dry-run` a s referencí ho porovnat nelze.

## Kolik to stojí

Orientačně **3–6 USD a 15–30 minut** za jeden plný běh (asi 12 volání modelů, dokument kolem
15 000 tokenů). Odhad není změřený; skutečnou spotřebu tokenů a cenu každého běhu najdete
v `prehled.html`.

## Příkazová řádka a vývoj

Hlavní příkazy jsou `--dry-run`, `--resume [SLOZKA]` a `compare [SLOZKA] --reference SOUBOR`.
Původní názvy `--nanecisto`, `--pokracovat` a `porovnat` dál fungují jako aliasy.
Pokyny k vývoji, struktuře kódu a testům najdete v [CONTRIBUTING.md](CONTRIBUTING.md).

# Režim „predplatne“: Claude přes `claude -p`, GPT přes `codex exec`

Datum: 2026-10-18. Ověřeno na Claude Code 2.1.302 a codex-cli 0.163.0 (`--help`, `claude auth status`,
`codex login status`, `codex features list`, `codex debug models`, `codex debug prompt-input`)
a v aktuální dokumentaci (code.claude.com/docs: headless, cli-reference, authentication, errors;
learn.chatgpt.com/docs: config-reference, non-interactive-mode, models; zdrojáky openai/codex).

## Cíl

Nový výchozí režim volá modely přes předplatné (Claude Max, ChatGPT), bez API klíčů a bez plateb
za API. Stávající `ClaudeModel` a `GptModel` (API) zůstávají beze změny jako `rezim: api`.
Oba nové adaptéry implementují protokol `Model` z úkolu 5 (`json`, `text`, `vyzvedni_spotrebu`),
takže smyčka, kroky, porovnání ani výstupy se nemění.

## Rozsah změn

| Soubor | Změna |
|---|---|
| `refiner/modely/podproces.py` (nový) | společné: vyčištěné prostředí, nalezení programu, spuštění se stdin a timeoutem, dočasné adresáře |
| `refiner/modely/claude_cli.py` (nový) | `ClaudeCliModel` |
| `refiner/modely/codex_cli.py` (nový) | `CodexModel` |
| `refiner/modely/chyby.py` | nové druhy chyb a služby, české hlášky (API hlášky beze změny) |
| `refiner/konfigurace.py`, `nastaveni.yaml` | `modely.rezim` a `modely.predplatne` |
| `refiner/cli.py` | továrna vybírá podle režimu; kontrola klíčů v `.env` jen v režimu `api` |
| `README.md`, `.env.example` | výchozí režim nepotřebuje `.env`; postup přihlášení `claude` a `codex login` |
| `tests/test_podproces.py`, `tests/test_claude_cli.py`, `tests/test_codex_cli.py`, úpravy `test_konfigurace`, `test_cli` | testy s falešným podprocesem |

| `refiner/data.py` | `Spotreba.predplatne: bool = False` |
| `refiner/vystup/prehled.py`, `sablony/prehled.html.j2` | cena „v předplatném“ (viz Spotřeba a cena) |

`kroky.py`, `smycka.py`, `porovnani.py` a `aplikace.py` se nemění.

## Konfigurace

```yaml
modely:
  # predplatne = Claude Code (předplatné Max) a Codex CLI (předplatné ChatGPT), bez API klíčů;
  # api = placené API s klíči v .env (oddíly claude a gpt níže).
  rezim: predplatne
  predplatne:
    claude: {model: claude-opus-5-5, effort: high, effort_extrakce: medium}
    codex: {model: gpt-6-astra, effort: high}
  claude: {...}   # beze změny, jen pro rezim: api
  gpt: {...}      # beze změny, jen pro rezim: api
  max_retries: 4  # jen API; CLI opakují dočasné chyby samy
  timeout_s: 1800 # platí pro oba režimy (jedno volání podprocesu)
```

- `rezim: Literal["predplatne", "api"] = "predplatne"`. Oddíl `predplatne` má výchozí hodnoty, aby
  šly načíst i kopie nastavení ze starších běhů (`extra="forbid"` zůstává).
- Effort pro Claude CLI je `low|medium|high|xhigh|max` (podle `claude --help`).
- Effort pro Codex je `low|medium|high|xhigh|max`. `ultra` („automatic task delegation“) a
  `none`/`minimal` validace odmítne.
- Ceny v `ceny_usd_za_milion` se v režimu předplatného nepoužijí (viz Spotřeba).

**Modely Codexu s ChatGPT přihlášením.** Katalog `codex debug models` je stažený s ChatGPT
identitou. Viditelné obecné modely jsou gpt-6.1-sol, gpt-6-astra, gpt-6-sol, gpt-6-luna,
gpt-5.6-sol, gpt-5.6-terra a gpt-5.6-luna. Žádný z nich není `-codex` varianta.
Jako výchozí zůstává gpt-6-astra, stejně jako v režimu API.

Být v katalogu ale ještě neznamená, že model půjde použít: komunita hlásí chybu „model is not
supported when using Codex with a ChatGPT account“. Proto má ostrý test ověřit právě nastavený model.

## Společný základ (`podproces.py`)

**Prostředí.** Kopie `os.environ` bez těchto proměnných (`load_dotenv` je mohl načíst z `.env`):

- **Claude:** `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL`,
  `ANTHROPIC_PROFILE`, `ANTHROPIC_FEDERATION_RULE_ID`, `ANTHROPIC_ORGANIZATION_ID`,
  `CLAUDE_CODE_USE_BEDROCK|VERTEX|FOUNDRY`, `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_CODE_SIMPLE`
  (= `--bare`, vynutí API klíč), `CLAUDE_CODE_EFFORT_LEVEL` (přebije `--effort`), `CLAUDECODE`
  a ostatní `CLAUDE_CODE_*` (vnořená relace).
- **Codex:** `OPENAI_API_KEY`, `CODEX_API_KEY` (u `exec` má přednost před ChatGPT),
  `CODEX_ACCESS_TOKEN`, `OPENAI_BASE_URL`, `OPENAI_FEDERATION_RULE_ID`, `OPENAI_IDENTITY_TOKEN_FILE`.
- **Ponechá se** `CLAUDE_CONFIG_DIR` a `CODEX_HOME`, protože určují, kde přihlášení leží.

Čištění se netýká jen „svých“ proměnných, ale obou sad pro oba nástroje.

**Kontrola přihlášení.** Jednou v konstruktoru adaptéru, ve stejném vyčištěném prostředí:

- **Claude:** `claude auth status`, JSON. Vyžaduje `loggedIn` a `authMethod == "claude.ai"`.
  Tím se zachytí i `apiKeyHelper` v nastavení, které proměnnou prostředí odstranit nejde.
  Jiná metoda ověření → `neprihlasen` s detailem.
- **Codex:** `codex login status`. Vyžaduje text „Logged in using ChatGPT“ (stderr, exit 0).

Konstruktor běží v `cli._spust` uvnitř `try`, takže `ChybaModelu` skončí českou hláškou a kódem 2
dřív, než se založí složka běhu.

**Nalezení programu.** Přednost má `prikaz` v konfiguraci (volitelný, výchozí `null`), jinak
`shutil.which`.

- `claude` je nativní `claude.exe`.
- `codex` je npm spouštěč `codex.cmd`, který jde přes cmd.exe (limit 8191 znaků, uvozovky).
  Spouštěč se proto přeloží na nativní
  `…\node_modules\@openai\codex\node_modules\@openai\codex-win32-x64\vendor\x86_64-pc-windows-msvc\bin\codex.exe`.
  Když tam není, použije se spouštěč (argumenty jsou krátké a bez uvozovek).
- Nenalezeno → `nenainstalovano`.

**Spuštění.** Prompt (zadání) jde přes stdin v UTF-8 a nikdy jako argument.

- Systémový prompt a schéma jdou souborem, protože `instrukce` obsahují celou poptávku a profil.
- Každé volání má vlastní `TemporaryDirectory`:
  - `prace/` je prázdný pracovní adresář podprocesu (`cwd`, u Codexu i `-C`),
  - `soubory/` drží systémový prompt, schéma a výstupní soubor.
- Výstup se dekóduje jako UTF-8 s `errors="replace"`.

**Timeout.** `Popen.communicate(timeout=timeout_s)`. Po vypršení se zabije celý strom procesů
(`taskkill /T /F /PID`, Codex má pod sebou další procesy) → `timeout`.

**Testovatelnost.** Funkce `spust(argv, stdin, env, cwd, timeout) -> Vysledek(kod, stdout, stderr)`
je injektovatelná (parametr konstruktoru, jako dnešní `klient`).

## Claude: `ClaudeCliModel`

```
claude -p --output-format json --no-session-persistence
       --model <model> --effort <effort | effort_extrakce z parametru>
       --system-prompt-file <soubory/instrukce.md>
       --tools "" --disallowedTools "mcp__*" --strict-mcp-config --safe-mode
       --permission-prompts none
       [--json-schema '<schéma>']            # jen json()
```

**Co přepínače dělají:**

- `--system-prompt-file` nahrazuje celý výchozí programátorský prompt.
- `--tools ""` vypne vestavěné nástroje. `--disallowedTools "mcp__*"` a `--strict-mcp-config`
  vypnou nástroje MCP.
- `--safe-mode` vypne CLAUDE.md, skills, pluginy, hooky a MCP. Na rozdíl od `--bare`
  zachovává přihlášení předplatným. `--bare` použít nejde, protože čte jen API klíč.
- Pojistkou navíc jsou proměnné `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`,
  `CLAUDE_CODE_DISABLE_ATTACHMENTS=1` a `CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS=1`.
  Uživatel má globální `~/.claude/CLAUDE.md`, který by se jinak do volání dostal.

**JSON.** Schéma `schema.model_json_schema()` jde inline, je nejvýš 2 KB. Validovaný objekt je
v `structured_output` a projde ještě `schema.model_validate`.

- `subtype == "error_max_structured_output_retries"` nebo chybějící `structured_output` →
  `nevalidni_vystup`.
- Chyba validace → `chyba_parsovani`. Obojí spustí stávající `s_opravou` v `kroky.py`.

**Text.** Pole `result`.

**Chyby.** Rozhoduje `is_error`, `subtype`, kód ukončení a text v `result` / `errors` / stderr.

| Text v chybě | Druh |
|---|---|
| `Not logged in`, `Login expired`, `Failed to authenticate` | `neprihlasen` |
| `You've hit your … limit · resets …` | `limit_predplatneho` (čas obnovení do detailu) |
| `Request rejected (429)`, `temporarily limiting`, `overloaded` | `pretizeni` |
| `not available with the Claude … plan`, `not found`, `not a recognized model id` | `model_nedostupny` |
| `stop_reason == "max_tokens"` | `uriznuto` |
| `api_error`, chyba sítě | `sit` |
| ostatní | `jina` (s ořezaným a anonymizovaným detailem) |

**Spotřeba.** Z `usage`: `input_tokens`, `output_tokens`, `cache_read_input_tokens`,
`cache_creation_input_tokens`. `total_cost_usd` je jen odhad klienta a ignoruje se.

## Codex: `CodexModel`

```
codex.exe exec --json --ephemeral --skip-git-repo-check --ignore-user-config --ignore-rules
      -s read-only -C <prace> -m <model>
      -c model_reasoning_effort=<effort> -c model_reasoning_summary=none
      -c model_instructions_file="<soubory/instrukce.md>"
      -c approval_policy=never -c web_search=disabled
      -c features.shell_tool=false -c project_doc_max_bytes=0
      -c include_permissions_instructions=false -c include_environment_context=false
      -c skills.include_instructions=false
      --disable plugins --disable apps --disable memories --disable hooks
      --disable image_generation --disable browser_use --disable computer_use
      -o <soubory/odpoved.txt>
      [--output-schema <soubory/schema.json>]   # jen json()
      -                                          # prompt ze stdin
```

**Co přepínače dělají:**

- `model_instructions_file` nahrazuje vestavěné instrukce. Hodnota je TOML řetězec ve
  dvojitých uvozovkách (`json.dumps(str(cesta))`), takže projde i cesta s mezerou, diakritikou
  nebo apostrofem.
- `--ignore-user-config` je nutné, protože uživatelův `config.toml` nastavuje `gpt-5.6-luna`.
  Model a effort proto jdou vždy explicitně.
- `project_doc_max_bytes=0` vypne načítání AGENTS.md.

**Známé omezení.** Shell `unified_exec` u gpt-6.x vypnout nejde („User opt-outs are ignored“).
Obranu tvoří tyto vrstvy:

- sandbox jen pro čtení,
- prázdný pracovní adresář,
- `approval_policy=never`, takže se na nic nečeká,
- instrukce bez úkolů pro nástroje.

Zápis souborů je tím vyloučený, čtení disku ne. Pro textový model je to přijatelné.

**JSON.** `--output-schema` je striktní: povinné všechny vlastnosti, `additionalProperties:false`.
Schéma vyrobí `openai.lib._pydantic.to_strict_json_schema(schema)`. Je to tatáž transformace, kterou
dnes implicitně používá `responses.parse` v `GptModel`, a projde u všech schémat projektu.
Funkce je interní, takže verze `openai` zůstává připnutá a test hlídá, že import funguje.
Text z `-o` projde `schema.model_validate_json`, chyby → `chyba_parsovani` → oprava.

**Text.** Obsah souboru `-o`.

**Události (`--json`, stdout).**

- `turn.completed.usage` → Spotřeba: `input_tokens`, `cached_input_tokens` jako `cache_cteni`,
  `output_tokens`.
- `turn.failed.error.message` nebo `error.message` → mapování chyb.

**Chyby.**

| Text v chybě | Druh |
|---|---|
| `You’ve hit your usage limit` (s typografickým apostrofem), `usage_limit_reached`, `quota_exceeded` | `limit_predplatneho` |
| `Not signed in`, `codex login` | `neprihlasen` |
| `is not supported when using Codex with a ChatGPT account` | `model_nedostupny` |
| `rate_limit_exceeded`, `server_overloaded` | `pretizeni` |
| `context_window_exceeded` | `jina` s vysvětlením |
| ostatní | `jina` |

**Parametr `effort` v `json()` Codex ignoruje**, stejně jako `GptModel`.

## Chyby a hlášky (`chyby.py`)

`Sluzba` se rozšíří o `"Claude Code"` a `"Codex"`. `DruhChyby` se rozšíří o `nenainstalovano`,
`neprihlasen`, `limit_predplatneho` a `model_nedostupny`. Nové hlášky:

- **nenainstalovano:** „Nástroj {sluzba} není nainstalovaný (příkaz {prikaz} nebyl nalezen).
  Nainstalujte ho podle README nebo v nastaveni.yaml přepněte modely.rezim na api.“
- **neprihlasen:** „Nástroj {sluzba} není přihlášený předplatným. Spusťte v příkazovém řádku
  {prihlaseni} a pak spusťte pokracovat.bat.“ (`claude` → /login, resp. `codex login`;
  u Claude s detailem, když je přihlášený jinak než předplatným)
- **limit_predplatneho:** „Vyčerpali jste limit předplatného u {sluzba}{detail: (obnoví se …)}.
  Po obnovení limitu spusťte pokracovat.bat.“
- **model_nedostupny:** „Model {model} není s vaším předplatným {sluzba} dostupný. Změňte ho
  v nastaveni.yaml v oddílu modely.predplatne.“
- **timeout:** stávající text („Služba {sluzba} neodpověděla včas…“) platí i pro nástroje.
- **uriznuto** pro Claude Code a Codex: varianta bez odkazu na limit v nastavení (u CLI ho
  nastavit nejde): „Odpověď modelu {sluzba} byla uříznutá (příliš dlouhá).“

`_KLICE` a `_LIMITY` dostanou položky pro nové služby. Stávající API hlášky a jejich testy se
nemění.

Hlášku „Model OpenAI vrátil neplatnou odpověď ani po opravě“ z `kroky._sluzba` (podle prefixu
`gpt`) zatím nechávám, protože kroky se měnit nemají. Název služby v ní je jen kosmetická
nepřesnost.

## CLI

- `_vychozi_tovarna` a `_vychozi_hodnotitel` vyberou podle `modely.rezim` buď
  `ClaudeCliModel` + `CodexModel`, nebo `ClaudeModel` + `GptModel`.
- Kontrola klíčů v `.env` proběhne jen pro `rezim: api`. Režim se čte z aktuálního
  `nastaveni.yaml` před kontrolou klíčů, platí i pro `--pokracovat` a `porovnat`, protože oddíl
  `modely` se bere vždy z repozitáře.
- `porovnat` v režimu předplatného potřebuje jen Codex.
- `--nanecisto` se nemění.

## Spotřeba a cena v přehledu (rozhodnuto: „v předplatném“)

Volání přes předplatné se neplatí po tokenech. Přehled u nich proto místo ceny napíše
„v předplatném“. Tokeny dál ukazuje.

**Data.** `Spotreba` dostane pole `predplatne: bool = False`.

- Oba nové adaptéry ho nastaví na `True`.
- Výchozí hodnota zajistí, že starší běhy se načtou jako API.
- `Spotreba.model` zůstává čistý název modelu.

**Přehled.** `vystup/prehled.py:_cena` sčítá řádky podle dvojice (model, `predplatne`).

- Řádek předplatného má cenu „v předplatném“. Do součtu USD se nepočítá a nenastaví `neznama`.
- Rozpoznání OpenAI podle prefixu `gpt` (`_je_openai`) se dál použije pro sloučení tokenů z cache.

**Šablona** `prehled.html.j2`, buňka Celkem:

- Jen předplatné: „v předplatném“.
- Jen API: beze změny („X USD“, případně „+ cena neznámá u některých modelů“).
- Smíšený běh: „X USD + část v předplatném“. Nastane, když se `modely.rezim` změní mezi
  přerušením a `--pokracovat`.
- Poznámka pod tabulkou dostane větu, že volání v předplatném se neúčtují po tokenech.

**Porovnání.** `porovnani.html.j2` cenu neukazuje, takže se nemění. Ověří se při implementaci.

**Testy.** `test_prehled` ověří řádek předplatného, buňku Celkem pro všechny tři případy
a načtení staré `Spotreba` bez pole `predplatne`.

## Testy (bez skutečných volání)

**Falešný `spust`** zaznamená argv, stdin, env a cwd a vrátí připravený `Vysledek`. Testy ověří:

- **Prompt a schéma:**
  - zadání je jen ve stdin, ne v argv,
  - systémový prompt je v souboru,
  - schéma u Codexu je striktní.
- **Prostředí:** env neobsahuje žádný z klíčů, ani když jsou v `os.environ`
  (monkeypatch obou sad). `CLAUDE_CONFIG_DIR` a `CODEX_HOME` zůstávají.
- **Pracovní adresář:** cwd je prázdný adresář, který po volání zmizí.
- **Přepínače:**
  - `--tools ""`, `--safe-mode`, `-s read-only` a `--ignore-user-config` jsou přítomné,
  - `--bare` přítomný není,
  - model a effort z konfigurace, u Claude `effort_extrakce` z parametru.
- **JSON:** úspěch, `structured_output` chybí, `error_max_structured_output_retries`, nevalidní
  JSON (vede na opravu přes `s_opravou`) a uříznutí.
- **Mapování chyb:** každý řádek obou tabulek chyb na správný druh a hlášku.
  Kontrola přihlášení: `authMethod: api_key` → `neprihlasen`.
- **Spotřeba:** z `usage`, resp. z `turn.completed`.
- **Program:** nenalezený program → `nenainstalovano`, přeložení `codex.cmd` → `codex.exe`
  (falešná adresářová struktura v `tmp_path`).

**Skutečný `spust`** dostane jako „program“ malý Python skript v `tmp_path`. Testy ověří, že
dorazí stdin v UTF-8 s diakritikou, že se předá env a cwd a že timeout zabije strom procesů.

**Ostatní testy:** `test_konfigurace` pokryje výchozí `rezim`, starou kopii nastavení bez oddílu
`predplatne` a odmítnutí `ultra`. `test_cli` ověří, že v režimu předplatného nevadí prázdný
`.env` a v režimu API se klíče kontrolují dál.

## Ostrý test (na konci, až po souhlasu)

**Než se spustí, zeptám se uživatele.** Pak proběhne po jednom volání `json()` každého adaptéru
s malým vstupem a schématem `VystupNalezitosti` nad dvouřádkovou poptávkou.

Ověří se:

- skutečně se používá přihlášení předplatným: `authMethod`, u Codexu chybí `CODEX_API_KEY`,
- `--json-schema` funguje při `--tools ""`,
- `model_instructions_file` opravdu nahrazuje výchozí prompt: odpověď neobsahuje nic
  programátorského a model nesahá na nástroje, což se pozná z událostí `item.*` u Codexu
  a `num_turns` u Claude,
- tvar výstupu odpovídá parserům,
- vybraný model je s ChatGPT přihlášením dostupný.

Odchylky se zapíšou do tohoto dokumentu a promítnou do testů.

## Otevřené body (ověří ostrý test)

- Kolik pokusů o strukturovaný výstup Claude CLI dělá a jestli `--json-schema` nepotřebuje
  `--max-turns` > 1.
- Přesný tvar chyby při vyčerpaném limitu v `claude -p --output-format json` (`is_error`,
  `subtype`, kód ukončení). Ověří se jen z textu, ostře to vyvolat nejde.
- Zda `--safe-mode` v `-p` opravdu potlačí CLAUDE.md. Pojistkou je `CLAUDE_CODE_DISABLE_CLAUDE_MDS`.

### Výsledky ostrého testu (2026-10-18, claude-opus-5-5 přes Claude Code 2.1.302, gpt-6-astra přes codex-cli 0.163.0)

- **Claude:** přihlášení `claude.ai`; `--json-schema` funguje při `--tools ""` (`structured_output` přítomen).
  `num_turns` = 2 a `stop_reason` = `tool_use` je normální (strukturovaný výstup jde přes pomocný nástroj),
  adaptér to nebere jako chybu. Spotřeba: 2 vstup, 2528 cache_zapis, 349 výstup. `total_cost_usd` se ignoruje.
  Ve výstupu nejsou stopy programátorského promptu ani CLAUDE.md; `web_search_requests` = 0.
- **Codex:** `Logged in using ChatGPT`; model gpt-6-astra je s ChatGPT přihlášením dostupný; žádný
  `command_execution` ani jiný nástroj; `turn.completed.usage` má `input_tokens`, `cached_input_tokens`,
  `cache_write_input_tokens`, `output_tokens`, `reasoning_output_tokens` (přebývající pole se ignoruje).
  `--disable plugins|apps|memories|hooks|image_generation|browser_use|computer_use` nehlásí neznámou funkci.
- **Odchylka:** `-c tools.view_image=false` Codex 0.163.0 nezná. Hlásil to jako `item.completed` typu `error`
  („Codex is ignoring 1 unrecognized configuration setting“), volání ale doběhlo. Přepínač odstraněn,
  testy: `test_argv_bez_nastaveni_ktere_codex_nezna`, `test_varovani_codexu_jako_item_error_neshodi_volani`.
- **Otevřené body:** počet pokusů Claude CLI o strukturovaný výstup a přesný tvar chyby při vyčerpaném limitu
  zůstávají neověřené (limit se ostře vyvolat nedá). Co hlásí `claude auth status` při nastaveném API klíči
  v settings.json, nebylo zkoušeno.

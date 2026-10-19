# Režim „predplatne“ – implementační plán

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Výchozí režim, který volá Claude přes `claude -p` (předplatné Max) a GPT přes `codex exec`
(předplatné ChatGPT) bez API klíčů. API adaptéry zůstávají jako `modely.rezim: api`.

**Architecture:** Dva nové adaptéry protokolu `Model` (`ClaudeCliModel`, `CodexModel`) nad společným
modulem `podproces.py`. Ten vyčistí prostředí, najde program, spustí ho se stdin a timeoutem
v prázdném dočasném adresáři. Výběr adaptéru je v `cli.py` podle `modely.rezim`. Přehled u volání
v předplatném píše místo ceny „v předplatném“.

**Tech Stack:** Python 3.12 (projekt ≥ 3.10), pydantic 2.14.1, openai 3.33.0 (jen
`openai.lib._pydantic.to_strict_json_schema`), pytest 9.1.1, subprocess. Ověřeno na Claude Code
2.1.302 a codex-cli 0.163.0.

**Spec:** `.claude/plans/2026-10-18-rezim-predplatne-design.md`. Přesné argv obou nástrojů,
tabulky chyb a seznam proměnných prostředí jsou tam. Plán na ně odkazuje a neopakuje je.

## Global Constraints

- **Bez API klíčů v podprocesu.** Podproces nikdy nedostane klíče ani přihlašovací proměnné
  ze seznamu v designu (oddíl „Prostředí“), ani když jsou v `os.environ` nebo v `.env`.
- **Prompt jen přes stdin v UTF-8.** Zadání nikdy nejde jako argument. Systémový prompt a schéma
  jdou souborem, schéma Claude výjimečně inline (≤ 2 KB).
- **Bez skutečných volání v testech.** Žádný test nespustí skutečný `claude` ani `codex`.
  `conftest.py` to vynutí (Task 4).
- **Hlášky do konzole jen česky.** Texty jsou pevné, viz Task 2.
- **`kroky.py`, `smycka.py`, `porovnani.py` a `aplikace.py` se nemění.** API adaptéry `claude.py`
  a `gpt.py` také ne.
- **Bez git operací.** Uživatel dělá git sám. U každého Checkpointu vypiš soubory a navrhni zprávu.
- **Ostrý test až po souhlasu.** Ostrý test (Task 8) se spouští jen po výslovném souhlasu
  uživatele.

## Review Focus

1. **Cesta k dočasným souborům s mezerou, diakritikou nebo apostrofem.** Např. `C:\Users\O'Brien Novák\…`.
   Codex musí dostat platnou TOML hodnotu `model_instructions_file`, Claude platnou cestu
   `--system-prompt-file`. → test v Task 6 (`tomllib` přečte přesnou cestu) a Task 5.
2. **Claude CLI skončí nenulovým kódem s holým textem místo JSON.** Např. `Error: …` nebo
   `Not logged in · Please run /login`. Očekávání: správný druh chyby, žádný pád na
   `json.loads`. → Task 5.
3. **Codex vypíše na stdout mezi JSONL i ne-JSON řádky** (varování, prázdné řádky).
   Očekávání: přeskočí se, spotřeba a chyby se přečtou. → Task 6.
4. **Klíč v prostředí s jinou velikostí písmen.** Windows nerozlišuje velikost písmen
   v názvech proměnných, takže `anthropic_api_key` v předaném dict musí také zmizet. → Task 4.
5. **Timeout u procesu, jehož podřízený proces drží otevřený stdout.** Bez zabití celého stromu
   by `communicate()` po `kill()` visel navždy. Očekávání: `VyprselCas` do pár sekund. → Task 4.

---

### Task 1: Konfigurace `modely.rezim` a `modely.predplatne`

**Files:**
- Modify: `refiner/konfigurace.py` (třídy kolem `NastaveniModelu`), `nastaveni.yaml` (oddíl `modely`)
- Test: `tests/test_konfigurace.py`

**Interfaces:**
- Produces (`refiner/konfigurace.py`):
  ```python
  EffortCodex = Literal["low", "medium", "high", "xhigh", "max"]
  class NastaveniClaudeCli(_Model):
      model: str = "claude-opus-5-5"; effort: EffortClaude = "high"
      effort_extrakce: EffortClaude = "medium"; prikaz: str | None = None
  class NastaveniCodex(_Model):
      model: str = "gpt-6-astra"; effort: EffortCodex = "high"; prikaz: str | None = None
  class NastaveniPredplatneho(_Model):
      claude: NastaveniClaudeCli = Field(default_factory=NastaveniClaudeCli)
      codex: NastaveniCodex = Field(default_factory=NastaveniCodex)
  class NastaveniModelu(_Model):   # stávající pole beze změny, navíc:
      rezim: Literal["predplatne", "api"] = "predplatne"
      predplatne: NastaveniPredplatneho = Field(default_factory=NastaveniPredplatneho)
  ```

- [ ] **Step 1: Napiš failing testy**

```python
def test_vychozi_rezim_je_predplatne(koren_repa):
    n = nacti_nastaveni(koren_repa / "nastaveni.yaml")
    assert n.modely.rezim == "predplatne"
    assert n.modely.predplatne.claude.model == "claude-opus-5-5"
    assert n.modely.predplatne.codex.model == "gpt-6-astra"
    assert n.modely.predplatne.claude.prikaz is None

def test_stara_kopie_bez_rezimu_se_nacte(tmp_path, koren_repa):
    # nastaveni.yaml bez řádků rezim a predplatne (kopie ze staršího běhu)
    ...
    assert n.modely.rezim == "predplatne" and n.modely.predplatne.codex.effort == "high"

@pytest.mark.parametrize("effort", ["ultra", "none", "minimal"])
def test_codex_effort_mimo_povolene_selze(tmp_path, koren_repa, effort):
    with pytest.raises(ChybaKonfigurace, match="modely.predplatne.codex.effort"): ...

def test_neznamy_rezim_selze(tmp_path, koren_repa):
    with pytest.raises(ChybaKonfigurace, match="modely.rezim"): ...
```

- [ ] **Step 2: Spusť:** `.venv/Scripts/python -m pytest tests/test_konfigurace.py -v`. Očekávání: nové testy FAIL.

- [ ] **Step 3: Implementuj třídy z Interfaces a uprav `nastaveni.yaml`**

Oddíl `modely` přesně podle designu (oddíl „Konfigurace“): komentář k `rezim`, řádek
`rezim: predplatne` a oddíl `predplatne` s `claude` (model, effort, effort_extrakce)
a `codex` (model, effort). U `max_retries` doplň komentář „jen API; CLI opakují dočasné chyby
samy“. `prikaz` se do YAML nepíše (výchozí `null`). Komentář u `predplatne` řekne, že se tím
dá zadat cesta k programu, když není v PATH.

- [ ] **Step 4: Spusť celou sadu:** `.venv/Scripts/python -m pytest -q`. Očekávání: vše PASS.

- [ ] **Step 5: Checkpoint**: `refiner/konfigurace.py`, `nastaveni.yaml`, `tests/test_konfigurace.py`. Zpráva: `feat: subscription mode settings (modely.rezim, modely.predplatne)`.

---

### Task 2: Chyby a hlášky nástrojů

**Files:**
- Modify: `refiner/modely/chyby.py`
- Test: `tests/test_chyby.py`

**Interfaces:**
- Produces:
  - `Sluzba = Literal["Anthropic", "OpenAI", "Claude Code", "Codex"]`
  - `DruhChyby` rozšířený o `"nenainstalovano", "neprihlasen", "limit_predplatneho", "model_nedostupny"`
  - `NASTROJE: frozenset[Sluzba] = frozenset({"Claude Code", "Codex"})`
  - `skryj_klice(text: str) -> str`: dnešní `_skryj_klice` zveřejněný (alias kvůli stávajícímu kódu může zůstat).
  - Konstruktor `ChybaModelu(druh, sluzba, detail="", surova_odpoved=None)` beze změny signatury.

**Přesné texty nových hlášek:**

| Druh | Text |
|---|---|
| `nenainstalovano` | „Nástroj {sluzba} není nainstalovaný (příkaz {prikaz} nebyl nalezen). Nainstalujte ho podle README, nebo v nastaveni.yaml přepněte modely.rezim na api.“ |
| `neprihlasen` | „Nástroj {sluzba} není přihlášený předplatným. Přihlaste se příkazem {prihlaseni} a spusťte nástroj znovu (přerušený běh dokončí pokracovat.bat).“ |
| `limit_predplatneho` | „Vyčerpali jste limit předplatného u {sluzba} ({detail}). Až se limit obnoví, spusťte pokracovat.bat.“ |
| `model_nedostupny` | „Model {detail} není s vaším předplatným {sluzba} dostupný. Změňte ho v nastaveni.yaml v oddílu modely.predplatne.“ |
| `uriznuto` (jen `sluzba in NASTROJE`) | „Odpověď modelu {sluzba} byla uříznutá (příliš dlouhá).“ |

**Hodnoty k doplnění:**

- `{prikaz}`: Claude Code → `claude`, Codex → `codex`.
- `{prihlaseni}`: Claude Code → `claude (v něm /login)`, Codex → `codex login`.
- U `model_nedostupny` je `detail` název modelu. U `limit_predplatneho` je to text nástroje,
  adaptéry ho plní vždy.
- `_KLICE` a `_LIMITY` se čtou přes `.get(sluzba, "")`, aby nové služby nespadly na `KeyError`.
- Ostatní druhy (`timeout`, `pretizeni`, `sit`, `jina`, `nevalidni_vystup`, `odmitnuti`)
  použijí stávající texty.

- [ ] **Step 1: Napiš failing testy**

```python
@pytest.mark.parametrize("sluzba,prikaz", [("Claude Code", "claude"), ("Codex", "codex")])
def test_nenainstalovano_jmenuje_prikaz(sluzba, prikaz):
    h = ChybaModelu("nenainstalovano", sluzba).hlaska
    assert f"příkaz {prikaz} nebyl nalezen" in h and "modely.rezim na api" in h

def test_neprihlasen_codex_rika_jak_se_prihlasit():
    assert "codex login" in ChybaModelu("neprihlasen", "Codex").hlaska

def test_limit_obsahuje_text_nastroje():
    h = ChybaModelu("limit_predplatneho", "Claude Code", "You've hit your session limit · resets 3:45pm").hlaska
    assert "resets 3:45pm" in h and "pokracovat.bat" in h

def test_model_nedostupny_jmenuje_model():
    assert "gpt-6-astra" in ChybaModelu("model_nedostupny", "Codex", "gpt-6-astra").hlaska

def test_uriznuto_nastroje_bez_odkazu_na_limit():
    h = ChybaModelu("uriznuto", "Codex").hlaska
    assert "uříznutá" in h and "nastaveni.yaml" not in h

def test_timeout_nastroje():
    assert "Claude Code neodpověděla včas" in ChybaModelu("timeout", "Claude Code").hlaska
```

- [ ] **Step 2: Spusť:** `.venv/Scripts/python -m pytest tests/test_chyby.py -v`. Očekávání: nové FAIL, stávající PASS.
- [ ] **Step 3: Implementuj** v `chyby.py` podle Interfaces a tabulky. Pro `uriznuto` u nástrojů použij malý dict přepisů `_HLASKY_NASTROJU` a nesahej na `HLASKY`.
- [ ] **Step 4: Spusť:** `.venv/Scripts/python -m pytest -q`. Očekávání: vše PASS.
- [ ] **Step 5: Checkpoint**: `refiner/modely/chyby.py`, `tests/test_chyby.py`. Zpráva: `feat: error kinds and Czech messages for CLI tools`.

---

### Task 3: Cena „v předplatném“ v přehledu

**Files:**
- Modify: `refiner/data.py` (`Spotreba`), `refiner/vystup/prehled.py` (`_cena`), `refiner/vystup/sablony/prehled.html.j2` (oddíl 6)
- Test: `tests/test_prehled.py`

**Interfaces:**
- Produces:
  - `Spotreba.predplatne: bool = False`. Docstring doplň o větu „True = volání přes předplatné (CLI), cena se neuvádí“.
  - `_cena(...)` vrací navíc klíče:
    - `"predplatne": bool`: je alespoň jeden řádek v předplatném,
    - `"jen_predplatne": bool`: jsou všechny řádky v předplatném a existuje alespoň jeden.
  - Řádky se slučují podle `(model, predplatne)` a mají klíč `"predplatne"`.
  - Řádek v předplatném má `cena == "v předplatném"`. Do `celkem` se nepočítá a `neznama`
    nenastaví.

- [ ] **Step 1: Napiš failing testy**

```python
def test_cena_predplatne_se_nepocita(zdroje):
    cena = _cena([Spotreba(krok="navrh", model="claude-opus-5-5", vstup=1000, vystup=500, predplatne=True),
                  Spotreba(krok="hodnoceni_1", model="gpt-6-astra", vstup=1000, vystup=500, predplatne=True)],
                 zdroje.konfigurace)
    assert [r["cena"] for r in cena["radky"]] == ["v předplatném", "v předplatném"]
    assert cena["jen_predplatne"] and not cena["neznama"] and cena["celkem"] == _desetinne(0.0)

def test_cena_smiseny_beh_rozdeli_radky(zdroje):
    # stejný model jednou přes API, jednou v předplatném → dva řádky
    ...
    assert len(cena["radky"]) == 2 and cena["predplatne"] and not cena["jen_predplatne"]

def test_stara_spotreba_bez_pole_je_api():
    assert Spotreba.model_validate({"krok": "x", "model": "m", "vstup": 1, "vystup": 1}).predplatne is False

def test_prehled_celkem_v_predplatnem(tmp_path, zdroje):   # vzor: test_prehled_cena_a_tokeny
    # běh se Spotreba(predplatne=True) → HTML obsahuje „v předplatném“ v řádku Celkem, ne „0,00 USD“
def test_prehled_celkem_smiseny(tmp_path, zdroje):
    # → „USD + část v předplatném“
```

- [ ] **Step 2: Spusť:** `.venv/Scripts/python -m pytest tests/test_prehled.py -v`. Očekávání: nové FAIL.
- [ ] **Step 3: Implementuj** `Spotreba.predplatne`, `_cena` a šablonu.
  - Buňka Celkem:
    - `jen_predplatne` → `v předplatném`,
    - jinak dnešní text a navíc ` + část v předplatném`, když je `predplatne`.
  - Pod `<p class="meta">` přidej, jen když je `cena.predplatne`, větu „Volání v předplatném
    (Claude Code, Codex) se neúčtují po tokenech, jejich cena se proto neuvádí.“
  - `porovnani.html.j2` zkontroluj grepem na `cena`: neměla by cenu zobrazovat. Pokud ano, uprav ji stejně.
- [ ] **Step 4: Spusť:** `.venv/Scripts/python -m pytest -q`. Očekávání: vše PASS.
- [ ] **Step 5: Checkpoint**: `refiner/data.py`, `refiner/vystup/prehled.py`, `refiner/vystup/sablony/prehled.html.j2`, `tests/test_prehled.py`. Zpráva: `feat: show subscription calls as "v předplatném" in overview`.

---

### Task 4: Společný základ `podproces.py` a pojistka v testech

**Files:**
- Create: `refiner/modely/podproces.py`, `tests/test_podproces.py`
- Modify: `tests/conftest.py`

**Interfaces:**
- Produces (`refiner/modely/podproces.py`):
  ```python
  @dataclass(frozen=True)
  class Vysledek:
      kod: int
      stdout: str
      stderr: str

  class VyprselCas(Exception): ...

  Spoustec = Callable[[list[str], str, dict[str, str], Path, float], Vysledek]
  #          (argv, stdin, env, cwd, timeout_s)

  def spust_proces(argv: list[str], stdin: str, env: dict[str, str], cwd: Path,
                   timeout_s: float) -> Vysledek: ...
  spust: Spoustec = spust_proces      # adaptéry berou `podproces.spust` v konstruktoru; conftest ho nahrazuje

  ODSTRANIT: tuple[str, ...]          # přesný seznam z designu (oddíl „Prostředí“), obě sady
  def ciste_prostredi(zdroj: Mapping[str, str] | None = None,
                      navic: Mapping[str, str] | None = None) -> dict[str, str]: ...
  def najdi_program(vychozi: str, nastaveny: str | None) -> Path | None: ...
  def nativni_codex(cesta: Path) -> Path: ...
  @contextmanager
  def docasne_adresare() -> Iterator[tuple[Path, Path]]: ...   # (prace, soubory)
  ```

**Chování:**

- **`ciste_prostredi`** vezme `zdroj` (výchozí `os.environ`) a odstraní:
  - názvy z `ODSTRANIT`,
  - vše, co začíná na `CLAUDE_CODE_`, a `CLAUDECODE`.
  Porovnává bez ohledu na velikost písmen. `CLAUDE_CONFIG_DIR` a `CODEX_HOME` ponechá.
  Nakonec přidá `navic`.
- **`spust_proces`:**
  - `Popen(argv, stdin/stdout/stderr=PIPE, cwd=cwd, env=env)`, prompt jako
    `stdin.encode("utf-8")`, výstup dekóduje `utf-8` s `errors="replace"`.
  - Při `TimeoutExpired` na Windows zavolá `taskkill /T /F /PID <pid>` (jinde `proc.kill()`),
    pak `communicate()` a vyhodí `VyprselCas`.
  - `FileNotFoundError` nechá projít.
- **`najdi_program`** zkusí `nastaveny`: existující cestu, jinak `shutil.which(nastaveny)`.
  Když `nastaveny` chybí, zkusí `shutil.which(vychozi)`. Nenalezeno → `None`.
- **`nativni_codex`:** pro `codex.cmd` vrátí
  `<adresář>/node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe`,
  pokud existuje, jinak `cesta` beze změny.
- **`docasne_adresare`:** `TemporaryDirectory(prefix="refiner-", ignore_cleanup_errors=True)`
  s podadresáři `prace/` (prázdný) a `soubory/`.

- [ ] **Step 1: Pojistka v `conftest.py`.** Do autouse fixture `_bez_site` přidej
  `monkeypatch.setattr(podproces, "spust", _zakaz_nastroj)`. `_zakaz_nastroj` vyhodí
  `RuntimeError("Test se pokusil spustit skutečný nástroj CLI")`.

- [ ] **Step 2: Napiš failing testy**

```python
def test_ciste_prostredi_odstrani_klice():
    env = ciste_prostredi({"ANTHROPIC_API_KEY": "sk-a", "anthropic_api_key": "sk-b", "OPENAI_API_KEY": "x",
                           "CODEX_API_KEY": "x", "CLAUDE_CODE_OAUTH_TOKEN": "x", "CLAUDE_CODE_SIMPLE": "1",
                           "CLAUDECODE": "1", "CLAUDE_CONFIG_DIR": "C:/c", "CODEX_HOME": "C:/x", "PATH": "p"},
                          navic={"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"})
    assert env == {"CLAUDE_CONFIG_DIR": "C:/c", "CODEX_HOME": "C:/x", "PATH": "p",
                   "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"}

def test_odstranit_obsahuje_vsechny_z_designu():
    assert {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY",
            "CODEX_ACCESS_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "ANTHROPIC_BASE_URL", "OPENAI_BASE_URL"} <= set(ODSTRANIT)

def test_stdin_utf8_s_diakritikou_a_dlouhy(tmp_path):
    # skript v tmp_path: přečte sys.stdin.buffer, zapíše délku a obsah zpět jako UTF-8 do stdout
    text = "Příliš žluťoučký kůň úpěl ďábelské ódy. " * 5000   # ~200 000 znaků
    v = spust_proces([sys.executable, str(skript)], text, ciste_prostredi(), tmp_path, 30)
    assert v.kod == 0 and v.stdout == text

def test_env_a_cwd_se_predaji(tmp_path): ...   # skript vypíše os.getcwd() a os.environ.get("X")

def test_timeout_zabije_i_podrizene_procesy(tmp_path):
    # skript spustí potomka (sleep 60, zdědí stdout) a sám spí 60 s
    start = time.monotonic()
    with pytest.raises(VyprselCas):
        spust_proces([sys.executable, str(skript)], "", ciste_prostredi(), tmp_path, 1)
    assert time.monotonic() - start < 15

def test_najdi_program_nastavena_cesta_ma_prednost(tmp_path): ...
def test_najdi_program_nenalezeno(monkeypatch): ...         # which → None → None
def test_nativni_codex_z_npm_spoustece(tmp_path): ...       # falešný strom node_modules → cesta k codex.exe
def test_nativni_codex_bez_exe_vrati_spoustec(tmp_path): ...
def test_docasne_adresare_prace_je_prazdna_a_zmizi(): ...
def test_conftest_blokuje_skutecny_nastroj():
    with pytest.raises(RuntimeError, match="skutečný nástroj"):
        podproces.spust(["claude"], "", {}, Path("."), 1)
```

Testy se skutečným `spust_proces` spouštějí jen `sys.executable` se skriptem v `tmp_path`.

- [ ] **Step 3: Spusť:** `.venv/Scripts/python -m pytest tests/test_podproces.py -v`. Očekávání: FAIL (modul neexistuje).
- [ ] **Step 4: Implementuj** `podproces.py` podle Interfaces a Chování.
- [ ] **Step 5: Spusť:** `.venv/Scripts/python -m pytest -q`. Očekávání: vše PASS a timeout test do 15 s.
- [ ] **Step 6: Checkpoint**: `refiner/modely/podproces.py`, `tests/test_podproces.py`, `tests/conftest.py`. Zpráva: `feat: subprocess helper with clean environment, stdin prompt and tree-kill timeout`.

---

### Task 5: `ClaudeCliModel`

**Files:**
- Create: `refiner/modely/claude_cli.py`, `tests/test_claude_cli.py`

**Interfaces:**
- Consumes: Task 1 `NastaveniModelu.predplatne.claude`, `timeout_s`. Task 2 `ChybaModelu`,
  `chyba_parsovani`, `skryj_klice`. Task 3 `Spotreba(predplatne=True)`. Task 4 `podproces.*`.
- Produces:
  ```python
  class ClaudeCliModel:          # implementuje refiner.modely.rozhrani.Model
      def __init__(self, nastaveni: NastaveniModelu, spust: Spoustec | None = None): ...
      nazev: str                 # = nastaveni.predplatne.claude.model
  def druh_chyby_claude(text: str) -> DruhChyby | None: ...   # tabulka z designu, bez uriznuto/sit
  ```

**Chování:**

- **Konstruktor:**
  - `spust or podproces.spust`.
  - `najdi_program("claude", prikaz)` → `None` → `ChybaModelu("nenainstalovano", "Claude Code")`.
  - `claude auth status` v `ciste_prostredi(navic=…)` s cwd = dočasná `prace` a timeoutem 60 s.
  - Vyžaduje `loggedIn` a `authMethod == "claude.ai"`, jinak `neprihlasen` s detailem
    `authMethod=<hodnota>`. Nečitelný JSON se bere jako nepřihlášení.
- **Volání `json()` a `text()`:**
  - `navic` = tři proměnné `CLAUDE_CODE_DISABLE_*` z designu.
  - argv přesně podle designu (oddíl Claude), `instrukce` jde do `soubory/instrukce.md`,
    stdin = `zadani`.
  - `json()`: `--effort` = `effort or n.effort`, schéma `json.dumps(schema.model_json_schema())`.
  - `text()`: `--effort` = `n.effort`, bez `--json-schema`.
- **Vyhodnocení:**
  - `VyprselCas` → `timeout`. `FileNotFoundError` → `nenainstalovano`.
  - Když stdout není JSON objekt:
    - `druh_chyby_claude(stdout + stderr)`, jinak `jina` s detailem `skryj_klice(...)[:500]`.
  - JSON objekt:
    - nejdřív zapiš Spotřebu z `usage`, pokud tam je,
    - pak při `is_error` nebo nenulovém kódu: `error_max_structured_output_retries` →
      `nevalidni_vystup`, jinak `druh_chyby_claude` nad `result` + `errors` + stderr,
      jinak `jina`,
    - `stop_reason == "max_tokens"` → `uriznuto`, `"refusal"` → `odmitnuti`,
    - `json()`: chybí `structured_output` → `nevalidni_vystup`. Jinak
      `schema.model_validate(structured_output)` a `ValidationError` → `chyba_parsovani`.
    - `text()`: `result`.
  - U `model_nedostupny` je detail název modelu, u `limit_predplatneho` text nástroje.

**Testovací data** (konstanty v testu):

- `OK_JSON`: `{"type":"result","subtype":"success","is_error":false,"result":"…",
  "structured_output":{…VystupNalezitosti…},"stop_reason":"end_turn","usage":{"input_tokens":100,
  "output_tokens":50,"cache_read_input_tokens":30,"cache_creation_input_tokens":20}}`
- `AUTH_OK`: `{"loggedIn":true,"authMethod":"claude.ai","apiProvider":"firstParty"}`

**Falešný spouštěč** odpovídá podle argv:

- `auth status` → `AUTH_OK`,
- jinak další odpověď z fronty,
- volání si zaznamená (argv, stdin, env, cwd) a v okamžiku volání i obsah `soubory/` a `prace/`.

- [ ] **Step 1: Napiš failing testy**

```python
def test_zadani_jen_ve_stdin_instrukce_v_souboru(): ...
    # "ZADANI-123" in stdin, ne v žádném prvku argv; obsah souboru za --system-prompt-file == instrukce
def test_prepinace_izolace():
    for p in ["-p", "--output-format", "json", "--no-session-persistence", "--safe-mode",
              "--strict-mcp-config", "--permission-prompts"]: assert p in argv
    assert argv[argv.index("--tools") + 1] == "" and "--bare" not in argv
    assert argv[argv.index("--disallowedTools") + 1] == "mcp__*"
def test_model_a_effort_z_konfigurace_a_extrakce(): ...   # json(effort="low") → --effort low; text → n.effort
def test_env_bez_klicu(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x"); monkeypatch.setenv("OPENAI_API_KEY", "sk-y")
    assert not {"ANTHROPIC_API_KEY", "OPENAI_API_KEY"} & set(k.upper() for k in env)
    assert env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
def test_cwd_prazdny_a_po_volani_smazany(): ...
def test_json_uspech_a_spotreba():
    assert vysledek == VystupNalezitosti(...)
    assert m.vyzvedni_spotrebu() == [Spotreba(krok="nalezitosti", model="claude-opus-5-5", vstup=100,
                                              vystup=50, cache_cteni=30, cache_zapis=20, predplatne=True)]
def test_json_bez_structured_output_je_nevalidni(): ...
def test_json_vycerpane_pokusy_schematu_je_nevalidni(): ...   # subtype error_max_structured_output_retries
def test_json_neplatny_vuci_schematu_vede_na_opravu():
    # 1. odpověď structured_output neplatný, 2. platný → kroky.s_opravou vrátí platný, 2 volání
def test_uriznuto_a_odmitnuti(): ...
@pytest.mark.parametrize("text,druh", [
    ("Not logged in · Please run /login", "neprihlasen"),
    ("Login expired · Please run /login", "neprihlasen"),
    ("Failed to authenticate. API Error: 401 OAuth token has expired", "neprihlasen"),
    ("You've hit your session limit · resets 3:45pm", "limit_predplatneho"),
    ("You've hit your weekly limit · resets Mon 12:00am", "limit_predplatneho"),
    ("Request rejected (429)", "pretizeni"),
    ("Server is temporarily limiting requests", "pretizeni"),
    ("Claude Opus is not available with the Claude Pro plan", "model_nedostupny"),
    ("Model claude-x is not a recognized model id", "model_nedostupny"),
])
def test_druh_chyby_claude(text, druh): assert druh_chyby_claude(text) == druh
def test_holy_text_s_nenulovym_kodem(): ...    # Vysledek(1, "Not logged in · Please run /login", "") → neprihlasen
def test_neznama_chyba_je_jina_bez_klicu(): ...  # "boom sk-abc123" → druh jina, "sk-abc123" not in hlaska
def test_timeout(): ...                         # spouštěč vyhodí VyprselCas → druh timeout, sluzba "Claude Code"
def test_nenainstalovano(monkeypatch): ...      # which → None
def test_prihlaseni_api_klicem_odmitne(): ...   # authMethod api_key → neprihlasen, detail obsahuje api_key
def test_cesta_s_mezerou_a_apostrofem(monkeypatch, tmp_path):
    # tempfile.tempdir = tmp_path / "O'Brien Novák" → soubor za --system-prompt-file existuje a má instrukce
```

- [ ] **Step 2: Spusť:** `.venv/Scripts/python -m pytest tests/test_claude_cli.py -v`. Očekávání: FAIL.
- [ ] **Step 3: Implementuj** `claude_cli.py` podle Interfaces a Chování. Logger `logging.getLogger(__name__)` zapíše argv bez instrukcí na úrovni DEBUG.
- [ ] **Step 4: Spusť:** `.venv/Scripts/python -m pytest -q`. Očekávání: vše PASS.
- [ ] **Step 5: Checkpoint**: `refiner/modely/claude_cli.py`, `tests/test_claude_cli.py`. Zpráva: `feat: Claude adapter over claude -p (subscription)`.

---

### Task 6: `CodexModel`

**Files:**
- Create: `refiner/modely/codex_cli.py`, `tests/test_codex_cli.py`

**Interfaces:**
- Consumes: jako Task 5, navíc `podproces.nativni_codex` a
  `openai.lib._pydantic.to_strict_json_schema`.
- Produces:
  ```python
  class CodexModel:              # implementuje Model
      def __init__(self, nastaveni: NastaveniModelu, spust: Spoustec | None = None): ...
      nazev: str                 # = nastaveni.predplatne.codex.model
  def druh_chyby_codex(text: str) -> DruhChyby | None: ...
  def precti_udalosti(stdout: str) -> tuple[dict | None, list[str], set[str]]: ...
      # (součet usage z turn.completed nebo None, zprávy z turn.failed/error, typy item.* )
  ```

**Chování:**

- **Konstruktor:**
  - `nativni_codex(najdi_program("codex", prikaz))`, nenalezeno → `nenainstalovano`.
  - `codex login status`: vyžaduje kód 0 a „Logged in using ChatGPT“ ve stdout+stderr,
    jinak `neprihlasen` s detailem = první řádek výstupu.
- **Volání `json()` a `text()`:**
  - argv přesně podle designu (oddíl Codex), `-C` = `prace`, poslední argument `-`.
  - Hodnota `model_instructions_file` je `json.dumps(str(cesta))`.
  - `-o soubory/odpoved.txt`.
  - `json()` navíc `--output-schema soubory/schema.json` s obsahem
    `json.dumps(to_strict_json_schema(schema))`.
  - Parametr `effort` se ignoruje.
- **Vyhodnocení:**
  - `VyprselCas` → `timeout`. `FileNotFoundError` → `nenainstalovano`.
  - `precti_udalosti` přeskočí ne-JSON řádky.
  - Spotřeba se zapíše vždy, když je usage: `vstup=input_tokens`,
    `cache_cteni=cached_input_tokens`, `vystup=output_tokens`, `predplatne=True`.
  - Typy `command_execution`, `file_change`, `mcp_tool_call` a `web_search` jen
    `_log.warning`. Volání neselže.
  - Nenulový kód nebo chybové zprávy → `druh_chyby_codex` nad zprávami + stderr, jinak `jina`.
  - Odpověď je obsah `-o`. Chybí nebo je prázdná → `nevalidni_vystup` (json) / `jina` (text).
  - `json()`: `schema.model_validate_json` a chyba → `chyba_parsovani`.

- [ ] **Step 1: Napiš failing testy**

```python
def test_argv_izolace_a_stdin():
    for p in ["exec", "--json", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config",
              "--ignore-rules", "-"]: assert p in argv
    assert argv[argv.index("-s") + 1] == "read-only" and argv[argv.index("-m") + 1] == "gpt-6-astra"
    assert "model_reasoning_effort=high" in argv and "features.shell_tool=false" in argv
    assert "ZADANI-123" in stdin and not any("ZADANI-123" in a for a in argv)
def test_instrukce_v_souboru_a_toml_cesta(monkeypatch, tmp_path):
    # tempfile.tempdir = tmp_path / "O'Brien Novák"
    hodnota = next(a for a in argv if a.startswith("model_instructions_file="))
    cesta = tomllib.loads(hodnota)["model_instructions_file"]
    assert Path(cesta).read_text(encoding="utf-8") == instrukce   # čteno uvnitř falešného spouštěče
def test_schema_je_striktni():
    s = json.loads(obsah_schema)
    assert s["additionalProperties"] is False and set(s["required"]) == set(s["properties"])
def test_strict_schema_pro_vsechna_schemata_projektu():
    for c in (VystupNalezitosti, Hodnoceni, Posouzeni, Srovnani, SeznamPrvku, Pokryti):
        to_strict_json_schema(c)
def test_env_bez_klicu(monkeypatch): ...  # CODEX_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY pryč; CODEX_HOME zůstane
def test_json_uspech_a_spotreba():
    # stdout: thread.started, item.completed agent_message,
    #   turn.completed usage {"input_tokens":2000,"cached_input_tokens":500,"output_tokens":300,"reasoning_output_tokens":100}
    assert spotreba == [Spotreba(krok="hodnoceni_1", model="gpt-6-astra", vstup=2000, vystup=300,
                                 cache_cteni=500, predplatne=True)]
def test_ne_json_radky_na_stdout_se_preskoci(): ...
def test_chybejici_vystupni_soubor_je_nevalidni(): ...
def test_neplatny_json_vede_na_opravu(): ...      # přes kroky.s_opravou, 2 volání
@pytest.mark.parametrize("text,druh", [
    ("You’ve hit your usage limit. Visit https://chatgpt.com/settings/usage to purchase more credits", "limit_predplatneho"),
    ("usage_limit_reached", "limit_predplatneho"),
    ("Not signed in. Please run 'codex login' to sign in with ChatGPT", "neprihlasen"),
    ("The 'gpt-x' model is not supported when using Codex with a ChatGPT account.", "model_nedostupny"),
    ("rate_limit_exceeded", "pretizeni"),
    ("server_overloaded", "pretizeni"),
])
def test_druh_chyby_codex(text, druh): ...
def test_turn_failed_mapuje_chybu(): ...          # kód 1 + turn.failed usage limit → limit_predplatneho
def test_pouziti_nastroje_jen_varuje(caplog): ... # item command_execution → warning v logu, výsledek vrácen
def test_login_status_api_klic_odmitne(): ...     # "Logged in using an API key - sk-***" → neprihlasen
def test_nativni_exe_misto_cmd(monkeypatch, tmp_path): ...   # which → codex.cmd ve falešném npm stromu → argv[0] je codex.exe
def test_timeout_a_nenainstalovano(): ...
```

`tomllib` je ve standardní knihovně od 3.11. Na 3.10 `pytest.importorskip("tomllib")`.

- [ ] **Step 2: Spusť:** `.venv/Scripts/python -m pytest tests/test_codex_cli.py -v`. Očekávání: FAIL.
- [ ] **Step 3: Implementuj** `codex_cli.py` podle Interfaces a Chování.
- [ ] **Step 4: Spusť:** `.venv/Scripts/python -m pytest -q`. Očekávání: vše PASS.
- [ ] **Step 5: Checkpoint**: `refiner/modely/codex_cli.py`, `tests/test_codex_cli.py`. Zpráva: `feat: GPT adapter over codex exec (ChatGPT subscription)`.

---

### Task 7: Zapojení do CLI a dokumentace

**Files:**
- Modify: `refiner/cli.py` (`_vychozi_tovarna`, `_vychozi_hodnotitel`, `_spust` kontrola klíčů, nápověda `porovnat`), `README.md`, `.env.example`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 1 `NastaveniModelu.rezim`, `nacti_nastaveni`. Task 5 `ClaudeCliModel`. Task 6 `CodexModel`.
- Produces:
  - `_vychozi_tovarna`: `nanecisto` → `demo_modely()`, `rezim == "api"` →
    `ClaudeModel, GptModel`, jinak `ClaudeCliModel, CodexModel`.
  - `_vychozi_hodnotitel`: `GptModel` nebo `CodexModel` podle režimu.
  - `_spust`: po `load_dotenv` a mimo `--nanecisto` načte `nacti_nastaveni(koren / "nastaveni.yaml")`.
    `ChybaKonfigurace` → hláška a kód 2. Klíče se kontrolují jen při `rezim == "api"`,
    se stejnými sadami jako dnes.
  - Nápověda `porovnat`: „porovná dokončený běh s referenční nabídkou (volá jen hodnotitele GPT)“.

- [ ] **Step 1: Uprav stávající testy klíčů.** `test_chybejici_klic`, `test_chybejici_klic_openai`
  a `test_klic_z_env_souboru` dostanou na začátek pomocnou funkci `_rezim_api(koren)`. Ta
  v kopii `nastaveni.yaml` nahradí `rezim: predplatne` za `rezim: api`.

- [ ] **Step 2: Napiš failing testy**

```python
def test_predplatne_nekontroluje_klice(koren):
    # bez .env, výchozí rezim, tovarna_modelu=lambda k, n: demo_modely()
    assert main([], koren=koren, vstup_fn=lambda _: "1", vystup=out, tovarna_modelu=...) == 0
    assert "ANTHROPIC_API_KEY" not in out.getvalue()

def test_vychozi_tovarna_podle_rezimu(koren, monkeypatch):
    # monkeypatch refiner.cli.ClaudeCliModel / CodexModel / ClaudeModel / GptModel na zapisovače tříd
    assert typy(_vychozi_tovarna(konf_predplatne, False)) == ("ClaudeCliModel", "CodexModel")
    assert typy(_vychozi_tovarna(konf_api, False)) == ("ClaudeModel", "GptModel")
    assert _vychozi_hodnotitel(konf_predplatne).__class__.__name__ == "CodexModel"

def test_predplatne_nepripraveny_nastroj_je_kod_2(koren, monkeypatch):
    # monkeypatch shutil.which → None; bez tovarna_modelu
    assert main([], ...) == 2 and "příkaz claude nebyl nalezen" in out.getvalue()
    assert not (koren / "output").exists() or not any((koren / "output").iterdir())

def test_neplatny_rezim_je_kod_2(koren): ...   # rezim: xyz → hláška obsahuje „modely.rezim“
```

- [ ] **Step 3: Spusť:** `.venv/Scripts/python -m pytest tests/test_cli.py -v`. Očekávání: nové FAIL.
- [ ] **Step 4: Implementuj** změny v `cli.py`.
- [ ] **Step 5: README a `.env.example`.**
  - README, krok 2 instalace: výchozí režim je předplatné a `.env` není potřeba. Postup:
    nainstalovat Claude Code a Codex CLI, `claude` + `/login` účtem s předplatným Max,
    `codex login` účtem ChatGPT. Ověření: `claude auth status` (`authMethod: claude.ai`)
    a `codex login status`.
  - Původní postup s API klíči přesuň do oddílu „Režim API (volitelný)“ s `modely.rezim: api`.
  - Upozornění: v režimu předplatného se klíče z `.env` do nástrojů nepředávají.
  - Řádek 132 o `porovnat` uprav podle nápovědy.
  - `.env.example`: úvodní komentář „Potřeba jen pro modely.rezim: api v nastaveni.yaml“.
- [ ] **Step 6: Spusť:** `.venv/Scripts/python -m pytest -q`. Očekávání: vše PASS.
- [ ] **Step 7: Checkpoint**: `refiner/cli.py`, `tests/test_cli.py`, `README.md`, `.env.example`. Zpráva: `feat: subscription mode as default in CLI; API mode optional`.

---

### Task 8: Ostrý test obou nástrojů (jen se souhlasem)

**Files:**
- Create: skript `ostry_test.py` ve scratchpadu (ne v repozitáři)
- Modify podle výsledku: `.claude/plans/2026-10-18-rezim-predplatne-design.md` (oddíl Otevřené body), testy z Task 5 a 6

- [ ] **Step 1: Zeptej se uživatele.** Nic nespouštěj, dokud neodpoví ano. Vysvětli, že proběhnou
  dvě krátká volání (jedno Claude, jedno Codex), každé s poptávkou o dvou řádcích. Čerpají
  z limitu předplatného, z API se neplatí nic.
- [ ] **Step 2: Skript.** Postaví `ClaudeCliModel` a `CodexModel` z repozitářového `nastaveni.yaml`
  a nad dvouřádkovou poptávkou zavolá každý jednou `json(..., VystupNalezitosti, krok="ostry_test")`
  s instrukcí z `prompty/nalezitosti.md`. Spouštěj s
  `env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY` a bez proměnných `CLAUDE_CODE_*` ze současné relace.
  Vypíše výsledek, spotřebu a pro diagnostiku surový stdout obou nástrojů. Ten získá spouštěčem,
  který obalí `podproces.spust_proces`.
- [ ] **Step 3: Vyhodnoť proti designu** (oddíl „Ostrý test“):
  - `structured_output` je přítomen při `--tools ""` a `num_turns`,
  - Codex neměl žádné `item` typu `command_execution`,
  - `turn.completed.usage` má očekávaná pole,
  - Codex nehlásí neznámou feature u `--disable …`,
  - model gpt-6-astra je s ChatGPT přihlášením dostupný,
  - odpověď nemá stopy programátorského promptu.
- [ ] **Step 4: Zapiš odchylky.** Do designu (oddíl Otevřené body → výsledky ostrého testu)
  a pro každou odchylku uprav adaptér a přidej test se skutečným (anonymizovaným) výstupem
  jako testovacími daty.
- [ ] **Step 5: Spusť:** `.venv/Scripts/python -m pytest -q`. Očekávání: vše PASS.
- [ ] **Step 6: Checkpoint**: případně změněné adaptéry, testy a design. Zpráva: `fix: adjust CLI adapters after live check`, nebo bez commitu, když nebyla žádná odchylka.

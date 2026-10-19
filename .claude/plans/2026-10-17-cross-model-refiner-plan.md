# Cross-model refiner – implementační plán

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prototyp v Pythonu, který z poptávky v `input/` vytvoří nabídku střídáním Claude (píše, sokratovsky posuzuje, reviduje) a GPT (hodnotí po kritériích), uloží celou historii do `output/<běh>/` a umí výsledek porovnat s referenční nabídkou.

**Architecture:** Smyčka (`smycka.py`) zná jen protokol `Model`; skuteční klienti (Claude, GPT) a falešné modely (testy, `--nanecisto`) ho implementují. Každý krok se okamžitě zapíše do složky běhu (`beh.py`) a stav do `data/beh.json`, takže přerušený běh jde dokončit. Skóre a splnění cíle počítají čisté funkce (`skore.py`) z validovaného JSON hodnotitele.

**Tech Stack:** Python ≥ 3.10, `anthropic` 1.15.0, `openai` 3.33.0, `pydantic` 2.14.1, `python-dotenv` 1.2.4, `PyYAML` 6.0.3, `pypandoc-binary` 1.17, `Jinja2` 3.1.6, `pytest` 9.1.1.

**Spec:** `.claude/plans/2026-10-17-cross-model-refiner-design.md` (dále „design“). Plán se o něj opírá; čti oba.

## Global Constraints

- Python ≥ 3.10 (lokálně 3.12.4). Verze v `requirements.txt` přesně pinované (viz Tech Stack).
- API klíče jen z `.env`: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`. Nikdy v kódu, konfiguraci ani výstupech.
- Názvy modelů jen v `nastaveni.yaml`: `claude-opus-5-5`, `gpt-6-astra`.
- Testy nikdy nevolají skutečná API: autouse fixture blokuje sockety a maže klíče z prostředí.
- Veškeré čtení a zápis souborů s explicitním `encoding="utf-8"` (výchozí kódování Windows je cp1250).
- Texty pro uživatele česky. Názvy souborů a složek, které nástroj vytváří, bez diakritiky.
- Generování nikdy nečte `examples/`; referenci používá jen příkaz `porovnat`.
- Celkové skóre a splnění cíle počítá kód, nikdy model.
- Pydantic třídy posílané modelům jako schéma (`VystupNalezitosti`, `Hodnoceni`, `Posouzeni`, `SeznamPrvku`, `Pokryti`, `Srovnani`) nemají výchozí hodnoty, `Optional` ani `ge`/`le` omezení (strict structured outputs je nemusí podporovat); rozsahy hlídá kód.
- Konstanty z designu: cílové skóre 9,5; max 3 revize + závěrečné hodnocení; váhy skupin A 0,50 / B 0,35 / C 0,15; minimum náležitosti 8; `max_navrhu` 10; skóre C = 10 při nule, jinak `max(1, 10 − 3 × počet)`; zkrácení přepisu nejvýš o 30 %.
- **Git:** implementátor nespouští žádné git příkazy. Kroky „Checkpoint“ znamenají: zastav se, vypiš uživateli soubory úkolu a navrhni commit zprávu.

## Review Focus

1. **Dočasný soubor Wordu v `input/`** (`~$Národní rozvojová banka.docx`, když je poptávka otevřená ve Wordu) – musí se ignorovat, ne nabídnout ve výběru nebo shodit převod. Test v Task 3.
2. **Konzole Windows v cp1250** – výpis `≥`, `→` nebo `–` nesmí shodit program (při průzkumu dat se to stalo). Test v Task 12.
3. **Cesta s diakritikou a mezerami** (`input/Národní rozvojová banka.docx`) přes pandoc – převod musí projít, složka běhu musí být ASCII. Test v Task 3.
4. **HTML nebo `<script>` ve výstupu modelu** (citace, zdůvodnění) v `prehled.html` / `porovnani.html` – musí být escapované. Test v Task 9.
5. **Ctrl+C během dlouhého volání** – běh se uloží jako přerušený a jde dokončit přes `pokracovat.bat`. Test v Task 10.

---

## Struktura souborů

```
pyproject.toml  requirements.txt  .env.example  .gitignore (úprava)  README.md (přepis)
nastaveni.yaml
profily/nabidka.yaml  profily/smernice.yaml
prompty/nalezitosti.md  navrh.md  hodnoceni.md  posouzeni.md  zapracovani.md
prompty/porovnani_kriteria.md  porovnani_prvky.md  porovnani_pokryti.md
podklady.priklad/profil_firmy.md
_priprava.bat  spustit.bat  pokracovat.bat  porovnat.bat
refiner/
  __init__.py  __main__.py  cli.py  aplikace.py
  konfigurace.py   načtení a validace YAML
  data.py          Pydantic modely dat (náležitosti, hodnocení, posouzení, skóre, spotřeba)
  skore.py         výpočet skóre, výběr finální verze
  vstup.py         nalezení vstupů, převod do Markdownu, podklady, slug
  fakta.py         placeholdery, podezřelé údaje
  beh.py           složka běhu, číslování, stav, obnovení
  kroky.py         prompty, volání modelů, validace a oprava
  smycka.py        orchestrace kroků
  porovnani.py     porovnání s referencí
  modely/__init__.py  rozhrani.py  chyby.py  falesne.py  claude.py  gpt.py
  vystup/__init__.py  markdown.py  diff.py  docx.py  prehled.py
  vystup/sablony/prehled.html.j2  porovnani.html.j2
tests/
  conftest.py  pomocne.py
  test_konfigurace.py  test_skore.py  test_vstup.py  test_fakta.py  test_beh.py
  test_chyby.py  test_falesne.py  test_kroky.py  test_vystup.py  test_smycka.py
  test_prehled.py  test_aplikace.py  test_claude.py  test_gpt.py  test_cli.py  test_porovnani.py
```

Spouštění testů ve všech úkolech: `.venv/Scripts/python -m pytest <cesta> -v`.

---

### Task 1: Kostra projektu a konfigurace

**Files:**
- Create: `pyproject.toml`, `requirements.txt`, `.env.example`, `nastaveni.yaml`, `profily/nabidka.yaml`, `profily/smernice.yaml`, `refiner/__init__.py`, `refiner/konfigurace.py`, `tests/conftest.py`, `tests/test_konfigurace.py`
- Modify: `.gitignore` (přidat `podklady/`; uživatel tam má necommitnutou úpravu – zachovat ji)

**Interfaces:**
- Produces (`refiner/konfigurace.py`, Pydantic modely s `extra="forbid"`):
  - `class ChybaKonfigurace(Exception)` – zpráva ve tvaru `"{soubor}, řádek {n}: {cesta}: {text}"` (řádek vynechat, když ho nejde určit)
  - `KriteriumProfilu(id: str, nazev: str, popis: str, vaha: float  # gt=0)`
  - `Profil(nazev: str, typ_dokumentu: str, pokyny_struktura: str, kriteria: list[KriteriumProfilu])`
  - `NastaveniClaude(model: str, effort: str, effort_extrakce: str, max_tokens_text: int, max_tokens_json: int, fallback: bool)`
  - `NastaveniGpt(model: str, effort: str, max_output_tokens: int)`
  - `NastaveniModelu(claude: NastaveniClaude, gpt: NastaveniGpt, max_retries: int, timeout_s: float)`
  - `NastaveniSmycky(cilove_skore: float, max_revizi: int  # ge=0, min_nalezitost: float, max_navrhu: int  # ge=1)`
  - `Cena(vstup: float, vystup: float)` (USD za 1M tokenů)
  - `Nastaveni(modely: NastaveniModelu, smycka: NastaveniSmycky, vahy_skupin: dict[Literal["A","B","C"], float], vychozi_profil: str, ceny_usd_za_milion: dict[str, Cena])`
  - `KriteriaKPoptavce(kriteria_navic: list[KriteriumProfilu] = [], vahy: dict[str, float] = {})`
  - `@dataclass(frozen=True) Konfigurace(nastaveni: Nastaveni, profil: Profil, profil_nazev: str, kriteria_profilu: list[KriteriumProfilu])` – `profil_nazev` = název souboru profilu bez přípony (`"nabidka"`), `kriteria_profilu` = profil sloučený s kritérii k poptávce
  - `nacti_konfiguraci(nastaveni: Path, profil: Path, kriteria: Path | None = None) -> Konfigurace`
  - `cesta_kriterii_k_poptavce(vstup: Path) -> Path | None` – `vstup.with_name(vstup.stem + ".kriteria.yaml")`, pokud existuje
  - `dostupne_profily(slozka: Path) -> list[str]` – seřazené názvy `*.yaml` bez přípony

- [ ] **Step 1: Založ projekt a prostředí**

`requirements.txt` s přesnými verzemi z Tech Stack. `pyproject.toml`: `[project] name = "cross-model-refiner"`, `requires-python = ">=3.10"`; `[tool.pytest.ini_options] testpaths = ["tests"]`, `pythonpath = ["."]`. `.env.example` se dvěma prázdnými klíči a českým komentářem, kde klíče získat. Pak:

Run: `python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt`
Expected: instalace bez chyb; `.venv/Scripts/python -c "import anthropic, openai, pypandoc; print(pypandoc.get_pandoc_version())"` vypíše verzi pandocu.

- [ ] **Step 2: Napiš `tests/conftest.py`**

Autouse fixture: `monkeypatch.setattr(socket.socket, "connect", ...)` vyhodí `RuntimeError("Test se pokusil o síťové spojení")`; `monkeypatch.delenv` obou klíčů (`raising=False`). Fixture `koren_repa` vrací `Path(__file__).parent.parent`.

- [ ] **Step 3: Napiš konfigurační soubory**

`nastaveni.yaml` (česky komentovaný):

```yaml
modely:
  claude: {model: claude-opus-5-5, effort: high, effort_extrakce: medium,
           max_tokens_text: 64000, max_tokens_json: 16000, fallback: true}
  gpt: {model: gpt-6-astra, effort: high, max_output_tokens: 32000}
  max_retries: 4
  timeout_s: 600
smycka: {cilove_skore: 9.5, max_revizi: 3, min_nalezitost: 8, max_navrhu: 10}
vahy_skupin: {A: 0.50, B: 0.35, C: 0.15}
vychozi_profil: nabidka
ceny_usd_za_milion:
  claude-opus-5-5: {vstup: 4.0, vystup: 20.0}
  gpt-6-astra: {vstup: 10.0, vystup: 50.0}
```

`profily/nabidka.yaml`: `nazev: Nabídka`, `typ_dokumentu: nabídka`, `pokyny_struktura` (obecná osnova nabídky: manažerské shrnutí, tabulka „požadavek poptávky → kde v nabídce“, cíle, metodika a etapy s výstupy a kritérii převzetí, harmonogram s milníky, cena a pracnost po etapách, součinnost, předpoklady a omezení, tým a reference; **nekopírovat specifika referenční nabídky**) a kritéria B1–B6 přesně podle designu kap. 4.1 (Konkrétnost 0,25 · Ověřitelnost výstupů 0,20 · Vnitřní konzistence 0,20 · Srozumitelnost pro zadavatele 0,15 · Hranice a rizika 0,10 · Jazyk a forma 0,10) s popisy z designu. `profily/smernice.yaml`: zárodek, 5–6 kritérií S1… (účel a působnost, role a odpovědnosti, postupy, kontrolní mechanismy, soulad s předpisy, jazyk), v komentáři „nevyladěno“.

- [ ] **Step 4: Napiš failing testy `tests/test_konfigurace.py`**

```python
def test_nacte_repo_konfiguraci(koren_repa):
    k = nacti_konfiguraci(koren_repa/"nastaveni.yaml", koren_repa/"profily"/"nabidka.yaml")
    assert k.nastaveni.smycka.cilove_skore == 9.5 and k.nastaveni.smycka.max_revizi == 3
    assert k.nastaveni.modely.claude.model == "claude-opus-5-5"
    assert [c.id for c in k.kriteria_profilu] == ["B1","B2","B3","B4","B5","B6"]
    assert k.profil_nazev == "nabidka"

def test_vaha_textem_hlasi_soubor_radek_a_cesky(tmp_path):
    # profil, kde vaha druhého kritéria je "vysoká" na řádku 9
    with pytest.raises(ChybaKonfigurace) as e: nacti_konfiguraci(..., profil)
    assert "profil.yaml" in str(e.value) and "řádek 9" in str(e.value)
    assert "musí být číslo" in str(e.value) and "vysoká" in str(e.value)

def test_neznama_polozka_preklep(tmp_path):        # "kriterja:" → "neznámá položka"
def test_chybejici_povinna_polozka(tmp_path):      # bez cilove_skore → "chybí povinná položka"
def test_vahy_skupin_musi_dat_soucet_1(tmp_path):  # A .5 B .5 C .15 → ChybaKonfigurace se "součet"
def test_neplatny_yaml_hlasi_radek(tmp_path):      # tab/neuzavřená závorka → "řádek"
def test_kriteria_k_poptavce_pridaji_a_prevazi(tmp_path, koren_repa):
    # kriteria_navic X1 (vaha .1), vahy {B6: .05}
    ids = [c.id for c in k.kriteria_profilu]; assert ids[-1] == "X1"
    assert next(c for c in k.kriteria_profilu if c.id == "B6").vaha == 0.05
def test_kriteria_k_poptavce_neznamy_id_ve_vahach(tmp_path):     # vahy {B9: .1} → ChybaKonfigurace
def test_id_kriteria_nesmi_zacinat_N(tmp_path):                  # N je vyhrazeno náležitostem
def test_duplicitni_id_kriteria(tmp_path):
def test_cesta_kriterii_k_poptavce(tmp_path):                    # a.docx + a.kriteria.yaml → cesta; jinak None
def test_dostupne_profily(koren_repa): assert dostupne_profily(koren_repa/"profily") == ["nabidka","smernice"]
```

- [ ] **Step 5: Run – expected FAIL** (`ModuleNotFoundError: refiner.konfigurace`)

- [ ] **Step 6: Implementuj `refiner/konfigurace.py`**

Číslo řádku pro chybu Pydanticu: `yaml.compose(text)` a projdi uzly podle `err["loc"]` (MappingNode → klíč, SequenceNode → index); vrať `node.start_mark.line + 1`. Chyby PyYAML mají `problem_mark.line`. České texty podle `err["type"]`: `missing` → „chybí povinná položka“, `float_parsing`/`float_type`/`int_parsing`/`int_type` → „musí být číslo, je ‚{input}‘“, `extra_forbidden` → „neznámá položka (překlep?)“, `greater_than`/`greater_than_equal` → „musí být větší než / alespoň {limit}“, `literal_error` → „musí být jedna z: {expected}“; jinak `err["msg"]`. Kontroly nad rámec schématu: součet `vahy_skupin` = 1 (tolerance 1e-6), unikátní ID, ID nezačíná `N`, klíče `vahy` existují.

- [ ] **Step 7: Run – expected PASS**

- [ ] **Step 8: Checkpoint** – soubory úkolu; zpráva: `feat: project skeleton and validated YAML configuration`

---

### Task 2: Datové modely a skóre

**Files:**
- Create: `refiner/data.py`, `refiner/skore.py`, `tests/pomocne.py`, `tests/test_skore.py`

**Interfaces:**
- Consumes: `KriteriumProfilu`, `Nastaveni` (Task 1)
- Produces (`refiner/data.py`, Pydantic):
  - `Nalezitost(id: str, text: str, citace: str)`; `VystupNalezitosti(nalezitosti: list[Nalezitost])`
  - `Kriterium(id: str, nazev: str, popis: str, vaha: float, skupina: Literal["A","B"])`
  - `sestav_kriteria(nalezitosti: list[Nalezitost], kriteria_profilu: list[KriteriumProfilu]) -> list[Kriterium]` – A z náležitostí (`nazev` = `text`, `popis` = citace, váha 1), pak B z profilu
  - `SkoreKriteria(id: str, skore: float, zduvodneni: str, dukaz: str)`
  - `VymyslenyFakt(citace: str, proc: str)`; `TvrzeniKOvereni(citace: str, proc: str)`
  - `Navrh(id: str, kriterium: str, misto: str, problem: str, navrh: str, priorita: Literal["vysoka","stredni","nizka"])`
  - `Hodnoceni(kriteria: list[SkoreKriteria], vymyslena_fakta: list[VymyslenyFakt], tvrzeni_k_overeni: list[TvrzeniKOvereni], navrhy: list[Navrh], celkovy_komentar: str)`
  - `Rozhodnuti(id_navrhu: str, opora: str, predpoklad: str, dusledek: str, rozhodnuti: Literal["prijato","castecne","odmitnuto"], zduvodneni: str, jak_zapracovat: str)`; `Posouzeni(rozhodnuti: list[Rozhodnuti], shrnuti: str)`
  - `VysledekSkore(a: float, b: float, c: float, celkem: float, cil_splnen: bool, duvody_nesplneni: list[str])`
  - `Spotreba(krok: str, model: str, vstup: int, vystup: int, cache_cteni: int = 0)`
- Produces (`refiner/skore.py`):
  - `skore_c(pocet_faktu: int) -> float`
  - `spocitej(hodnoceni: Hodnoceni, kriteria: list[Kriterium], nastaveni: Nastaveni) -> VysledekSkore`
  - `vyber_finalni(celkova_skore: dict[int, float]) -> int` – klíč = číslo verze
  - `format_skore(x: float) -> str` – `9.5 → "9,5"`
- Produces (`tests/pomocne.py`): `nastaveni_test() -> Nastaveni` (repo `nastaveni.yaml`), `kriteria_test(n_nalezitosti=3) -> list[Kriterium]` (N1–N3 + B1–B6 z repo profilu), `hodnoceni(zaklad: float = 8.0, prepsat: dict[str, float] | None = None, fakta: int = 0, navrhy: int = 2, kriteria: list[Kriterium] | None = None) -> Hodnoceni` (všem kritériím `zaklad`, vybraným `prepsat`; výchozí kritéria `kriteria_test()`), `posouzeni(h: Hodnoceni, rozhodnuti: str = "prijato") -> Posouzeni`

- [ ] **Step 1: Napiš failing testy `tests/test_skore.py`**

```python
def test_skore_c(): assert [skore_c(n) for n in (0,1,2,3,4)] == [10, 7, 4, 1, 1]

def test_vazeny_vypocet_a_zaokrouhleni_half_up():
    # A: N1..N3 = 9; B: všechna 9; fakta 0  → 0.5*9 + 0.35*9 + 0.15*10 = 9.15 → 9.2
    v = spocitej(hodnoceni(9.0), kriteria_test(), nastaveni_test())
    assert (v.a, v.b, v.c, v.celkem) == (9.0, 9.0, 10.0, 9.2)

def test_b_je_vazeny_prumer():
    # B1 (0.25)=10, ostatní B = 8  → B = 0.25*10 + 0.75*8 = 8.5
def test_cil_splnen():                       # hodnoceni(9.5): 4.75 + 3.325 + 1.5 = 9.575 → 9.6, cil True
def test_cil_blokuje_nalezitost_pod_8():     # hodnoceni(10, {"N2": 7.5}) → cil False, "N2" v duvody_nesplneni
def test_cil_blokuje_vymysleny_fakt():       # hodnoceni(10, fakta=1): 5 + 3.5 + 1.05 = 9.55 → 9.6, ale cil False, "vymyšlen" v důvodech
def test_cil_pod_prahem():                   # hodnoceni(9.2): 4.6 + 3.22 + 1.5 = 9.32 → 9.3, cil False, "9,3 < 9,5" v důvodech
def test_vyber_finalni_nejvyssi_pri_shode_pozdejsi():
    assert vyber_finalni({1: 7.0, 2: 8.8, 3: 8.1, 4: 8.8}) == 4
    assert vyber_finalni({1: 7.0, 2: 8.8, 3: 8.1}) == 2
def test_format_skore(): assert format_skore(9.5) == "9,5" and format_skore(10.0) == "10,0"
def test_sestav_kriteria_poradi_a_skupiny():  # N* skupina A váha 1, pak B1..B6 skupina B
```

- [ ] **Step 2: Run – expected FAIL**

- [ ] **Step 3: Implementuj `data.py`, `skore.py`, `tests/pomocne.py`**

Počítej v `Decimal(str(x))`, zaokrouhli `quantize(Decimal("0.1"), ROUND_HALF_UP)`; porovnání s cílem nad zaokrouhleným celkem. A = prostý průměr skóre kritérií skupiny A, B = vážený průměr (normalizovaný součtem vah), C = `skore_c(len(vymyslena_fakta))`. Hodnocení bez kritéria skupiny A/B → ta skupina = 0 (validace v Task 6 tomu brání). Důvody česky s `format_skore`.

- [ ] **Step 4: Run – expected PASS**

- [ ] **Step 5: Checkpoint** – zpráva: `feat: data models and score computation`

---

### Task 3: Vstup a kontrola faktů

**Files:**
- Create: `refiner/vstup.py`, `refiner/fakta.py`, `tests/test_vstup.py`, `tests/test_fakta.py`

**Interfaces:**
- Produces (`refiner/vstup.py`):
  - `class ChybaVstupu(Exception)`
  - `PODPOROVANE_PRIPONY = (".docx", ".md", ".txt")`
  - `najdi_vstupy(slozka: Path) -> list[Path]` – seřazené podle názvu; ignoruje `~$*`, skryté soubory, `*.kriteria.yaml` a nepodporované přípony
  - `nacti_jako_markdown(cesta: Path) -> str` – DOCX: `pypandoc.convert_file(str(cesta), "gfm")`; MD/TXT: `utf-8-sig`, při `UnicodeDecodeError` `cp1250`; prázdný výsledek → `ChybaVstupu("Soubor … neobsahuje žádný text.")`
  - `nacti_podklady(slozka: Path) -> str` – všechny podporované soubory kromě `sablona.docx`, každý pod nadpisem `## Podklad: <název>`; chybějící složka → `""`
  - `slug(text: str, max_delka: int = 60) -> str` – bez diakritiky (`unicodedata.normalize("NFKD")`), malá písmena, ne-alfanumerické → `-`, zkrácené
- Produces (`refiner/fakta.py`):
  - `najdi_placeholdery(md: str) -> list[str]` – obsahy `[DOPLNIT: …]` i holé `[DOPLNIT]` (→ `""`), bez duplicit, v pořadí výskytu
  - `class PodezrelyUdaj(BaseModel): druh: Literal["castka","ico","email","telefon","jmeno","url"]; hodnota: str`
  - `podezrele_udaje(dokument: str, zdroje: str) -> list[PodezrelyUdaj]` – údaj se hlásí, jen když jeho normalizovaná podoba (bez mezer a NBSP) není v normalizovaných zdrojích; obsah placeholderů se ignoruje

- [ ] **Step 1: Napiš failing testy**

```python
# test_vstup.py
def test_najdi_vstupy_ignoruje_docasne_soubory_wordu(tmp_path):   # Review Focus 1
    for n in ["Národní rozvojová banka.docx", "~$rodní rozvojová banka.docx", ".skryty.md",
              "a.kriteria.yaml", "obrazek.png", "b.md"]: (tmp_path/n).write_bytes(b"x")
    assert [p.name for p in najdi_vstupy(tmp_path)] == ["Národní rozvojová banka.docx", "b.md"]

def test_docx_s_diakritikou_v_nazvu(tmp_path):                     # Review Focus 3
    # vytvoř DOCX pandocem z MD s odrážkou a tabulkou, ulož jako "Národní rozvojová banka.docx"
    md = nacti_jako_markdown(tmp_path/"Národní rozvojová banka.docx")
    assert "Nabídka proto musí obsahovat" in md and "|" in md and "- " in md

def test_txt_v_cp1250(tmp_path):     # "Poptávka – žluťoučký kůň".encode("cp1250") → přečteno správně
def test_md_s_bom(tmp_path):         # BOM se nevrací v textu
def test_prazdny_vstup(tmp_path):    # "   \n" → ChybaVstupu, zpráva obsahuje název souboru
def test_podklady_spoji_soubory_bez_sablony(tmp_path):  # profil_firmy.md + sablona.docx → jen profil, s nadpisem
def test_podklady_chybi(tmp_path): assert nacti_podklady(tmp_path/"neni") == ""
def test_slug(): assert slug("Národní rozvojová banka") == "narodni-rozvojova-banka"

# test_fakta.py
def test_placeholdery():
    md = "Cena [DOPLNIT: sazba za MD] … IČ [DOPLNIT: IČ] … [DOPLNIT: sazba za MD] … [DOPLNIT]"
    assert najdi_placeholdery(md) == ["sazba za MD", "IČ", ""]
def test_podezrele_castky_a_ico():
    zdroje = "Sazba 15 000 Kč za MD."
    dok = "Sazba 15 000 Kč. Cena 187 500 Kč. IČ 12345678. Kontakt jan@firma.cz, +420 777 123 456."
    druhy = {(u.druh, u.hodnota) for u in podezrele_udaje(dok, zdroje)}
    assert ("castka", "187 500 Kč") in druhy and not any(h.startswith("15 000") for _, h in druhy)
    assert {"ico", "email", "telefon"} <= {d for d, _ in druhy}
def test_podezrele_jmeno_s_titulem():   # "Ing. Jan Novák" není ve zdrojích → druh "jmeno"
def test_nbsp_ve_zdroji_se_shoduje():  # "15 000 Kč" ve zdroji = "15 000 Kč" v dokumentu
def test_placeholder_neni_podezrely(): # "[DOPLNIT: IČ 12345678]" → nic
```

- [ ] **Step 2: Run – expected FAIL**

- [ ] **Step 3: Implementuj `vstup.py` a `fakta.py`**

Regexy pro `fakta.py`: částka `\d{1,3}(?:[  .]\d{3})*(?:,\d+)?\s?(?:Kč|CZK)`; IČ `\b\d{8}\b`; e-mail; telefon `(?:\+420[  ]?)?\d{3}[  ]?\d{3}[  ]?\d{3}`; jméno `\b(?:Ing|Mgr|Bc|JUDr|PhDr|RNDr|MUDr|doc|prof)\.\s+[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][a-záčďéěíňóřšťúůýž]+(?:\s+[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][a-záčďéěíňóřšťúůýž]+)?`; URL `https?://\S+`.

- [ ] **Step 4: Run – expected PASS**

- [ ] **Step 5: Checkpoint** – zpráva: `feat: input conversion and fact checks`

---

### Task 4: Složka běhu, stav a obnovení

**Files:**
- Create: `refiner/beh.py`, `tests/test_beh.py`

**Interfaces:**
- Consumes: `slug` (Task 3), `Spotreba`, `VysledekSkore` (Task 2)
- Produces (`refiner/beh.py`):
  - `ZaznamKroku(cislo: int, soubor: str, data: str | None)` (Pydantic)
  - `StavBehu(vstup: str, profil: str, vytvoreno: datetime, ukonceno: datetime | None, stav: Literal["bezi","dokoncen","prerusen"], duvod_ukonceni: str | None, chyba: str | None, finalni_verze: int | None, kroky: dict[str, ZaznamKroku], skore: dict[str, VysledekSkore], spotreba: list[Spotreba], varovani: list[str])`
  - `class Beh` s atributy `slozka: Path`, `stav: StavBehu` a metodami:
    - `@classmethod novy(cls, output: Path, nazev_vstupu: str, profil: str, ted: datetime) -> Beh` – složka `YYYY-MM-DD_HHMM_<slug(stem)>`, při kolizi `_2`, `_3`…; vytvoří `data/`
    - `@classmethod otevri(cls, slozka: Path) -> Beh`
    - `zapis(krok: str, nazev: str, obsah: str, data: BaseModel | None = None) -> Path` – soubor `NN_nazev` (NN = další číslo, dvě číslice), data do `data/NN_<nazev bez přípony>.json`; zaznamená krok a uloží stav
    - `zapis_k(krok: str, nazev: str, obsah: str) -> Path` – soubor se stejným číslem jako už zapsaný `krok` (např. `06_navrh_v2_zmeny.html`)
    - `zapis_pevny(relativni_cesta: str, obsah: str | bytes) -> Path` – bez čísla (`prehled.html`, `FINALNI_*.md`, `data/…`)
    - `hotovo(krok: str) -> bool`; `text(krok: str) -> str`; `data(krok: str, typ: type[T]) -> T`
    - `pridej_spotrebu(polozky: list[Spotreba]) -> None`; `pridej_varovani(text: str) -> None`; `uloz_skore(cislo: int, skore: VysledekSkore) -> None`
    - `ukonci(stav: Literal["dokoncen","prerusen"], duvod: str | None = None, chyba: str | None = None, finalni_verze: int | None = None) -> None`
    - `uloz() -> None` – `data/beh.json` atomicky (zápis do `beh.json.tmp` + `os.replace`)
  - Konstanta `SLOZKA_KONFIGURACE = "data/konfigurace"`

- [ ] **Step 1: Napiš failing testy `tests/test_beh.py`**

```python
T = datetime(2026, 10, 17, 14, 32)
def test_nazev_slozky_bez_diakritiky(tmp_path):
    b = Beh.novy(tmp_path, "Národní rozvojová banka", "nabidka", T)
    assert b.slozka.name == "2026-10-17_1432_narodni-rozvojova-banka" and (b.slozka/"data").is_dir()
def test_kolize_prida_priponu(tmp_path):  # druhý novy() ve stejné minutě → "…_2"
def test_cislovani_v_poradi_vzniku(tmp_path):
    b.zapis("poptavka", "poptavka.md", "x"); b.zapis("nalezitosti", "nalezitosti.md", "y", data=VystupNalezitosti(nalezitosti=[]))
    p = b.zapis("navrh_1", "navrh_v1.md", "z"); d = b.zapis_k("navrh_1", "navrh_v1_zmeny.html", "<p>")
    assert p.name == "03_navrh_v1.md" and d.name == "03_navrh_v1_zmeny.html"
    assert (b.slozka/"data"/"02_nalezitosti.json").exists()
def test_otevri_obnovi_stav_a_data(tmp_path):
    # zapis hodnoceni s daty → Beh.otevri(...).data("hodnoceni_1", Hodnoceni) == původní; hotovo("hodnoceni_1")
def test_stav_se_uklada_po_kazdem_zapisu(tmp_path):  # po zapis() má beh.json krok, bez volání uloz()
def test_atomicky_zapis_nenecha_tmp(tmp_path):        # po uloz() neexistuje beh.json.tmp
def test_ukonci_prerusen(tmp_path):                   # stav "prerusen", chyba uložena, ukonceno nastaveno
def test_spotreba_a_skore_se_prictou(tmp_path):       # pridej_spotrebu 2× → 2 položky po otevri()
```

- [ ] **Step 2: Run – expected FAIL**

- [ ] **Step 3: Implementuj `refiner/beh.py`**

- [ ] **Step 4: Run – expected PASS**

- [ ] **Step 5: Checkpoint** – zpráva: `feat: run folder with numbered steps and resumable state`

---

### Task 5: Rozhraní modelů, chyby a falešné modely

**Files:**
- Create: `refiner/modely/__init__.py`, `refiner/modely/rozhrani.py`, `refiner/modely/chyby.py`, `refiner/modely/falesne.py`, `tests/test_chyby.py`, `tests/test_falesne.py`

**Interfaces:**
- Consumes: `Spotreba` (Task 2)
- Produces (`refiner/modely/rozhrani.py`):
  ```python
  class Model(Protocol):
      nazev: str
      def json(self, instrukce: str, zadani: str, schema: type[T], *, krok: str, effort: str | None = None) -> T: ...
      def text(self, instrukce: str, zadani: str, *, krok: str) -> str: ...
      def vyzvedni_spotrebu(self) -> list[Spotreba]: ...   # vrátí nasbírané a vyprázdní
  ```
  `instrukce` = stabilní část (prompt + zdroje, cachuje se), `zadani` = proměnlivá část (dokument, návrhy).
- Produces (`refiner/modely/chyby.py`):
  - `DruhChyby = Literal["klic","kredit","pretizeni","sit","timeout","nevalidni_vystup","uriznuto","odmitnuti","jina"]`
  - `class ChybaModelu(Exception)` s atributy `druh: DruhChyby`, `sluzba: Literal["Anthropic","OpenAI"]`, `hlaska: str`, `detail: str`, `surova_odpoved: str | None`; konstruktor `ChybaModelu(druh, sluzba, detail="", surova_odpoved=None)` sestaví `hlaska` z `HLASKY`
  - `HLASKY: dict[DruhChyby, str]` – přesné texty:
    - `klic`: „Klíč {klic} v souboru .env chybí nebo je neplatný.“ (`{klic}` = `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` podle služby)
    - `kredit`: „Došel kredit u {sluzba}. Dobijte kredit a spusťte pokracovat.bat.“
    - `pretizeni`: „Služba {sluzba} je přetížená, zkuste to za pár minut a spusťte pokracovat.bat.“
    - `sit`: „Nepodařilo se spojit se službou {sluzba}. Zkontrolujte připojení a spusťte pokracovat.bat.“
    - `timeout`: „Služba {sluzba} neodpověděla včas. Zkuste to znovu přes pokracovat.bat.“
    - `nevalidni_vystup`: „Model {sluzba} vrátil neplatnou odpověď ani po opravě. Surová odpověď je ve složce data/.“
    - `uriznuto`: „Odpověď modelu {sluzba} byla uříznutá (příliš dlouhá) ani po opakování.“
    - `odmitnuti`: „Model {sluzba} úlohu odmítl (kategorie: {detail}).“
    - `jina`: „Neočekávaná chyba služby {sluzba}: {detail}“
  - `prevod_vyjimky(exc: Exception, sluzba: Literal["Anthropic","OpenAI"]) -> ChybaModelu`
- Produces (`refiner/modely/falesne.py`):
  - `Odpoved = BaseModel | dict | str | Exception | Callable[[str, str], BaseModel | dict | str]`
  - `class FalesnyModel(odpovedi: dict[str, list[Odpoved]], nazev: str = "falesny")` – klíč = přesný `krok` (`"hodnoceni_2"`), jinak část před prvním `_` (`"hodnoceni"`); odebírá odpovědi zepředu; vyčerpáno → `AssertionError("Falešný model nemá odpověď pro krok …")`; `Exception` vyhodí; `dict` validuje do `schema`; `Callable` dostane `(instrukce, zadani)`. Atribut `volani: list[tuple[str, str, str]]` (krok, instrukce, zadání). Každé volání přidá `Spotreba(krok, nazev, 1000, 500)`.

- [ ] **Step 1: Napiš failing testy**

```python
# test_chyby.py – výjimky se staví skutečnými třídami SDK nad httpx2
REQ = httpx2.Request("POST", "https://api.example/v1")
def resp(code): return httpx2.Response(code, request=REQ)

@pytest.mark.parametrize("exc,sluzba,druh", [
    (anthropic.AuthenticationError("x", response=resp(401), body=None), "Anthropic", "klic"),
    (anthropic.RateLimitError("x", response=resp(429), body=None), "Anthropic", "pretizeni"),
    (anthropic.InternalServerError("x", response=resp(529), body=None), "Anthropic", "pretizeni"),
    (anthropic.APITimeoutError(request=REQ), "Anthropic", "timeout"),
    (anthropic.APIConnectionError(request=REQ), "Anthropic", "sit"),
    (anthropic.BadRequestError("Your credit balance is too low", response=resp(400), body=None), "Anthropic", "kredit"),
    (openai.AuthenticationError("x", response=resp(401), body=None), "OpenAI", "klic"),
    (openai.RateLimitError("x", response=resp(429), body={"code": "insufficient_quota"}), "OpenAI", "kredit"),
    (openai.RateLimitError("x", response=resp(429), body={"code": "rate_limit_exceeded"}), "OpenAI", "pretizeni"),
    (openai.APITimeoutError(request=REQ), "OpenAI", "timeout"),
    (ValueError("??"), "OpenAI", "jina"),
])
def test_prevod_vyjimky(exc, sluzba, druh): assert prevod_vyjimky(exc, sluzba).druh == druh

def test_hlaska_klic_jmenuje_promennou():
    assert "OPENAI_API_KEY" in ChybaModelu("klic", "OpenAI").hlaska
def test_hlaska_odmitnuti_s_kategorii(): assert "cyber" in ChybaModelu("odmitnuti", "Anthropic", "cyber").hlaska

# test_falesne.py
def test_json_dict_se_validuje_do_schematu():
def test_presny_klic_ma_prednost_pred_prefixem():  # {"hodnoceni_2": [a], "hodnoceni": [b]}
def test_vyjimka_se_vyhodi():
def test_callable_dostane_instrukce_a_zadani():
def test_vycerpane_odpovedi_assertion():
def test_spotreba_se_vyzvedne_a_vyprazdni():
```

- [ ] **Step 2: Run – expected FAIL**

- [ ] **Step 3: Implementuj**

Rozlišení kreditu: OpenAI `getattr(exc, "code", None) == "insufficient_quota"` (případně `body["code"]`); Anthropic `BadRequestError` / `PermissionDeniedError` se zprávou obsahující „credit balance“. Ověř v nainstalovaných SDK (`inspect.signature`), že konstruktory výjimek v testu odpovídají; když se liší, uprav test, ne mapování druhů. Pořadí `isinstance` od nejkonkrétnější třídy (`APITimeoutError` je podtřída `APIConnectionError`).

- [ ] **Step 4: Run – expected PASS**

- [ ] **Step 5: Checkpoint** – zpráva: `feat: model protocol, error mapping and fake models`

---

### Task 6: Prompty a kroky

**Files:**
- Create: `prompty/nalezitosti.md`, `prompty/navrh.md`, `prompty/hodnoceni.md`, `prompty/posouzeni.md`, `prompty/zapracovani.md`, `refiner/kroky.py`, `tests/test_kroky.py`

**Interfaces:**
- Consumes: Task 1 (`Konfigurace`), Task 2 (data modely), Task 5 (`Model`, `ChybaModelu`, `FalesnyModel`)
- Produces (`refiner/kroky.py`):
  - `@dataclass(frozen=True) Zdroje(poptavka: str, podklady: str, konfigurace: Konfigurace, prompty: Path)`
  - `vykresli_prompt(slozka: Path, nazev: str, **promenne: str) -> str` – `string.Template(...).substitute(...)`; chybějící proměnná → `ChybaKonfigurace` se jménem souboru a proměnné
  - `extrahuj_nalezitosti(model: Model, zdroje: Zdroje) -> tuple[list[Nalezitost], list[str]]` – vrací (náležitosti, varování)
  - `napis_navrh(model: Model, zdroje: Zdroje, nalezitosti: list[Nalezitost]) -> str`
  - `ohodnot(model: Model, zdroje: Zdroje, kriteria: list[Kriterium], dokument: str, odmitnute: list[tuple[Navrh, Rozhodnuti]], krok: str) -> tuple[Hodnoceni, list[str]]`
  - `posud(model: Model, zdroje: Zdroje, nalezitosti: list[Nalezitost], dokument: str, hodnoceni: Hodnoceni, krok: str) -> Posouzeni`
  - `zapracuj(model: Model, zdroje: Zdroje, nalezitosti: list[Nalezitost], dokument: str, hodnoceni: Hodnoceni, posouzeni: Posouzeni, krok: str) -> str`
  - `zkontroluj_hodnoceni(h: Hodnoceni, kriteria: list[Kriterium]) -> list[str]`; `zkontroluj_posouzeni(p: Posouzeni, h: Hodnoceni) -> list[str]`; `zkontroluj_prepis(stary: str, novy: str, hodnoceni: Hodnoceni, posouzeni: Posouzeni) -> list[str]`
  - `prijate(posouzeni: Posouzeni) -> list[Rozhodnuti]` – `prijato` a `castecne`

**Proměnné promptů** (šablona = `instrukce`; `zadani` skládá kód pod pevnými nadpisy `## Dokument`, `## Návrhy hodnotitele`, `## Přijaté návrhy k zapracování`):

| Prompt | Proměnné |
|---|---|
| `nalezitosti.md` | `poptavka` |
| `navrh.md` | `typ_dokumentu`, `pokyny_struktura`, `poptavka`, `podklady`, `nalezitosti`, `kriteria` |
| `hodnoceni.md` | `typ_dokumentu`, `poptavka`, `podklady`, `kriteria`, `max_navrhu`, `odmitnute` |
| `posouzeni.md` | `poptavka`, `podklady`, `nalezitosti` |
| `zapracovani.md` | `poptavka`, `podklady`, `nalezitosti` |

Prázdné `podklady` se vykreslí jako „(Profil firmy nebyl dodán – všechna fakta o dodavateli označ [DOPLNIT: …].)“; prázdné `odmitnute` jako „(žádné)“.

**Povinný obsah promptů** (formulace na implementátorovi, česky):
- `nalezitosti.md`: vytáhni explicitní požadavky (seznamy „musí obsahovat“, „žádáme o zaslání“, rozsah plnění), sluč duplicity, ID `N1…`, `citace` = **doslovný** úryvek z poptávky.
- `navrh.md`: tabulka tří druhů obsahu z designu kap. 4.2 (fakt ze zdrojů / návrh dodavatele / neznámý fakt → `[DOPLNIT: co a proč]`); cenu smí spočítat jen jako pracnost × sazba z podkladů; pokrýt každou náležitost; čistý Markdown s nadpisy `#`/`##`, tabulky v Markdownu; česky, profesní tón; vrátit jen dokument.
- `hodnoceni.md`: hodnoť každé kritérium zvlášť 1–10 v krocích 0,5 s kotvami (10 = nelze zlepšit, 8 = drobné nedostatky, 5 = podstatné nedostatky, 1 = chybí); `dukaz` = citace z dokumentu nebo „chybí“; definice vymyšleného faktu, líného placeholderu a pravidlo pro odkazy na předpisy (→ `tvrzeni_k_overeni`) z designu kap. 4.2; nejvýš `${max_navrhu}` konkrétních návrhů s novým zněním; dříve odmítnuté návrhy opakovat jen s novým argumentem; celkové skóre nepočítat.
- `posouzeni.md`: u každého návrhu tři otázky z designu kap. 3.2 (opora / předpoklad / důsledek), rozhodnutí `prijato`/`castecne`/`odmitnuto`, zdůvodnění, `jak_zapracovat`; návrh vyžadující vymyšlený fakt přijmout jen jako `[DOPLNIT: …]`; každý návrh právě jedno rozhodnutí.
- `zapracovani.md`: zapracuj jen přijaté návrhy podle `jak_zapracovat`, nic jiného neměň, zachovej nadpisy, vrať celý dokument v Markdownu bez komentáře.

**Validace a oprava:** každý krok s JSON nebo kontrolou volá model nejvýš 2×. Když `zkontroluj_*` vrátí chyby nebo model vyhodí `ChybaModelu(druh="nevalidni_vystup")`, druhé volání dostane k `zadani` připojené „## Oprava\nPředchozí odpověď byla neplatná: <chyby>“. Při druhém selhání `ChybaModelu("nevalidni_vystup", sluzba, detail=chyby, surova_odpoved=...)`; `sluzba` se odvodí z `model.nazev` (začíná `gpt` → OpenAI, jinak Anthropic).

**Pravidla kontrol:**
- `zkontroluj_hodnoceni`: každé kritérium ze vstupu právě jednou, žádné navíc; skóre v 1–10 a násobek 0,5; unikátní ID návrhů; `Navrh.kriterium` existuje.
- `ohodnot` po úspěšné kontrole: více než `max_navrhu` návrhů → ponechá prvních `max_navrhu` podle priority (vysoka > stredni > nizka, stabilně) a vrátí varování.
- `extrahuj_nalezitosti`: náležitost, jejíž `citace` (po normalizaci bílých znaků) není v poptávce, se zahodí s varováním; nezůstane-li žádná → `ChybaModelu("nevalidni_vystup", …)`. Volá model s `effort=konfigurace.nastaveni.modely.claude.effort_extrakce`.
- `zkontroluj_posouzeni`: ke každému ID návrhu právě jedno rozhodnutí, žádné neznámé ID.
- `zkontroluj_prepis`: každý řádek začínající `# ` ze starého dokumentu je i v novém; nový má aspoň 70 % délky starého, pokud žádný přijatý návrh (`navrh` nebo `jak_zapracovat`) neobsahuje „zkrát“ nebo „odstran“; nový není prázdný.

- [ ] **Step 1: Napiš failing testy `tests/test_kroky.py`**

```python
def test_vsechny_prompty_se_vykresli(koren_repa):
    # každý prompt z tabulky s danými proměnnými → bez KeyError a bez zbylého "${"
def test_chybejici_promenna_v_promptu(tmp_path):   # šablona s ${neznama} → ChybaKonfigurace se jménem souboru
def test_nalezitosti_zahodi_vymyslenou_citaci(zdroje):
    m = FalesnyModel({"nalezitosti": [{"nalezitosti": [
        {"id": "N1", "text": "Harmonogram", "citace": "harmonogram a hlavní milníky realizace"},
        {"id": "N2", "text": "Pojištění", "citace": "doklad o pojištění odpovědnosti"}]}]})
    n, var = extrahuj_nalezitosti(m, zdroje)
    assert [x.id for x in n] == ["N1"] and "N2" in var[0]
def test_nalezitosti_pouziji_effort_extrakce(zdroje):  # zaznamenaný effort == "medium"
def test_hodnoceni_chybejici_kriterium_opravi_druhym_volanim(zdroje):
    # 1. odpověď bez B3, 2. kompletní → výsledek OK, 2 volání, ve 2. zadání "B3" a "## Oprava"
def test_hodnoceni_dvakrat_neplatne_vyhodi_chybu_se_surovou_odpovedi(zdroje):
def test_hodnoceni_skore_mimo_rozsah(): assert zkontroluj_hodnoceni(hodnoceni(8, {"N1": 11}), kriteria_test()) != []
def test_hodnoceni_skore_ne_nasobek_pul():  # hodnoceni(8, {"B2": 7.3}) → chyba
def test_hodnoceni_orizne_navrhy_podle_priority(zdroje):  # 12 návrhů, max 10 → 10, všechny "vysoka" zůstaly, varování
def test_odmitnute_navrhy_jsou_v_instrukci(zdroje):       # text odmítnutého návrhu a důvod v instrukce
def test_posouzeni_chybejici_rozhodnuti(): # 3 návrhy, 2 rozhodnutí → chyba s ID
def test_prepis_zmizel_nadpis(): assert zkontroluj_prepis("# A\n# B\nx", "# A\nx", h, p) != []
def test_prepis_zkraceni_bez_navrhu(): # nový má 50 % → chyba
def test_prepis_zkraceni_s_navrhem():  # přijatý návrh „zkrátit kap. 3“ → OK
def test_zapracovani_dostane_jen_prijate(zdroje):  # odmítnutý návrh není v zadání, přijatý a castecne ano
```

Fixture `zdroje` v `tests/pomocne.py`: `zdroje_test(koren_repa) -> Zdroje` s poptávkou obsahující větu „harmonogram a hlavní milníky realizace“, prázdnými podklady, repo konfigurací a `prompty = koren_repa/"prompty"`.

- [ ] **Step 2: Run – expected FAIL**

- [ ] **Step 3: Napiš prompty a implementuj `refiner/kroky.py`**

- [ ] **Step 4: Run – expected PASS**

- [ ] **Step 5: Checkpoint** – zpráva: `feat: prompts and validated loop steps with one repair attempt`

---

### Task 7: Markdown výstupy, diff a DOCX export

**Files:**
- Create: `refiner/vystup/__init__.py`, `refiner/vystup/markdown.py`, `refiner/vystup/diff.py`, `refiner/vystup/docx.py`, `tests/test_vystup.py`

**Interfaces:**
- Consumes: Task 2 data modely, `format_skore`
- Produces:
  - `nalezitosti_md(nalezitosti: list[Nalezitost], varovani: list[str]) -> str`
  - `hodnoceni_md(cislo: int, h: Hodnoceni, skore: VysledekSkore, kriteria: list[Kriterium]) -> str` – nadpis „Hodnocení N“, souhrn A/B/C/celkem a splnění cíle s důvody, tabulka kritérií (ID, název, skóre, zdůvodnění, důkaz), vymyšlená fakta, tvrzení k ověření, návrhy, komentář
  - `posouzeni_md(cislo: int, h: Hodnoceni, p: Posouzeni) -> str` – pro každý návrh: znění návrhu, opora, předpoklad, důsledek, **rozhodnutí**, zdůvodnění, jak zapracovat; nahoře počty přijato/částečně/odmítnuto
  - `diff_html(stary: str, novy: str, popis_stary: str, popis_novy: str) -> str` – `difflib.HtmlDiff(wrapcolumn=100).make_file(..., context=True, numlines=3, charset="utf-8")`
  - `exportuj_docx(md: str, cil: Path, sablona: Path | None) -> None` – `pypandoc.convert_text(md, "docx", format="gfm", outputfile=str(cil), extra_args=["--reference-doc=<sablona>"] if sablona else [])`

- [ ] **Step 1: Napiš failing testy**

```python
def test_hodnoceni_md_obsahuje_skore_a_duvody():
    md = hodnoceni_md(2, h, spocitej(h, k, n), k)
    assert "Hodnocení 2" in md and "9,2" in md and "B3" in md and "Vnitřní konzistence" in md
def test_hodnoceni_md_svislitko_v_textu_nerozbije_tabulku():   # zdůvodnění "a | b" → escapováno "\|"
def test_posouzeni_md_pocty_a_rozhodnuti():  # 2 přijaté, 1 odmítnutý → "Přijato: 2", "Odmítnuto: 1", důvod u odmítnutého
def test_diff_html_utf8_a_zmena():
    html = diff_html("Cena: 100 Kč\n", "Cena: 120 Kč\n", "v1", "v2")
    assert 'charset=utf-8' in html.lower() and "120" in html and "v2" in html
def test_exportuj_docx_s_tabulkou(tmp_path):
    exportuj_docx("# Nabídka\n\n| A | B |\n|---|---|\n| 1 | 2 |\n", tmp_path/"x.docx", None)
    assert nacti_jako_markdown(tmp_path/"x.docx").count("|") >= 6
def test_exportuj_docx_se_sablonou(tmp_path):  # šablona vytvořená `pandoc --print-default-data-file reference.docx`
```

- [ ] **Step 2: Run – expected FAIL**

- [ ] **Step 3: Implementuj**

- [ ] **Step 4: Run – expected PASS**

- [ ] **Step 5: Checkpoint** – zpráva: `feat: markdown reports, html diff and docx export`

---

### Task 8: Smyčka

**Files:**
- Create: `refiner/smycka.py`, `tests/test_smycka.py`

**Interfaces:**
- Consumes: `Beh` (Task 4), `Model`/`FalesnyModel` (Task 5), kroky (Task 6), renderery (Task 7), `spocitej`, `vyber_finalni`, `sestav_kriteria`
- Produces (`refiner/smycka.py`):
  - `@dataclass VysledekBehu(duvod: Literal["cil_splnen","limit_revizi","zadna_zmena"], finalni_verze: int, skore: dict[int, VysledekSkore])` – klíč = číslo hodnocení = číslo hodnocené verze
  - `spust_smycku(beh: Beh, zdroje: Zdroje, pisatel: Model, hodnotitel: Model, hlaseni: Callable[[str], None]) -> VysledekBehu`

**Algoritmus** (design kap. 3.3); ID kroků v `beh` a soubory:

| Krok | Volání | Soubor |
|---|---|---|
| `nalezitosti` | `extrahuj_nalezitosti` (pisatel) | `nalezitosti.md` + data `VystupNalezitosti`; varování → `beh.pridej_varovani` |
| `navrh_1` | `napis_navrh` | `navrh_v1.md` |
| `hodnoceni_k` | `ohodnot` (hodnotitel) | `hodnoceni_k.md` + data; `beh.uloz_skore(k, …)` |
| `posouzeni_k` | `posud` | `posouzeni_k.md` + data |
| `navrh_{k+1}` | `zapracuj` | `navrh_v{k+1}.md` + `zapis_k(…, "navrh_v{k+1}_zmeny.html", diff_html(...))` |

Pro k = 1 … `max_revizi + 1`: hodnocení → cíl splněn ⇒ `cil_splnen`; k = `max_revizi + 1` ⇒ `limit_revizi`; posouzení → žádné přijaté ⇒ `zadna_zmena`; jinak zapracování. Je-li krok `beh.hotovo(...)`, načte se z `beh` místo volání (obnovení); seznam odmítnutých návrhů se skládá i z načtených posouzení. Po každém kroku `beh.pridej_spotrebu(pisatel.vyzvedni_spotrebu() + hodnotitel.vyzvedni_spotrebu())`. Hlášení před každým modelovým krokem `[i/celkem] <popis>…`, kde `celkem = 2 + 3·max_revizi + 1` (12), a po hodnocení `hotovo, skóre X,X`. Výjimky smyčka nechytá.

- [ ] **Step 1: Napiš failing testy `tests/test_smycka.py`**

Do `tests/pomocne.py` přidej (používají je i Task 9, 10, 12, 13):
- `beh_test(tmp_path: Path, zdroje: Zdroje) -> Beh` – nový běh s už zapsaným krokem `poptavka` (`01_poptavka.md`), jako v reálném toku;
- `skript(skore_po_hodnocenich: list[float], rozhodnuti: str = "prijato") -> tuple[FalesnyModel, FalesnyModel]` – odpovědi pro všechny kroky; náležitosti N1–N3 s citacemi, které jsou doslova v poptávce ze `zdroje_test`; hodnocení k = `hodnoceni(skore_po_hodnocenich[k-1])`.

```python
def test_cil_splnen_v_prvnim_hodnoceni(tmp_path):
    v = spust_smycku(beh, zdroje, *skript([9.8]), hlaseni=lambda s: None)
    assert v.duvod == "cil_splnen" and v.finalni_verze == 1
    assert [p.name for p in sorted(beh.slozka.glob("0*"))] == [
        "01_poptavka.md", "02_nalezitosti.md", "03_navrh_v1.md", "04_hodnoceni_1.md"]
def test_cil_splnen_ve_druhem(tmp_path):              # [7.0, 9.8] → 2 hodnocení, 1 revize, finální 2
def test_tri_revize_a_zaverecne_hodnoceni(tmp_path):
    pis, hod = skript([7.0, 8.0, 8.5, 9.0])
    v = spust_smycku(...)
    assert v.duvod == "limit_revizi" and len(v.skore) == 4
    assert [k for k, *_ in hod.volani] == ["hodnoceni_1", "hodnoceni_2", "hodnoceni_3", "hodnoceni_4"]
    assert sum(1 for k, *_ in pis.volani if k.startswith("navrh_")) == 4   # v1 + 3 revize
    assert (beh.slozka/"06_navrh_v2_zmeny.html").exists()
def test_nic_neprijato_ukonci_bez_dalsiho_hodnoceni(tmp_path):  # rozhodnuti="odmitnuto" → "zadna_zmena", 1 hodnocení
def test_pokles_skore_vybere_drivejsi_verzi(tmp_path):          # [7.0, 9.0, 8.0, 8.5] → finální 2
def test_odmitnute_navrhy_jdou_do_dalsiho_hodnoceni(tmp_path):  # castecne/odmitnuto mix → text odmítnutého v instrukci hodnoceni_2
def test_obnoveni_nevola_hotove_kroky(tmp_path):
    # 1. běh: hodnotitel vyhodí ChybaModelu("pretizeni") v hodnoceni_2 → výjimka propadne
    # 2. běh nad Beh.otevri(): nové falešné modely mají odpovědi jen od hodnoceni_2 dál → doběhne
    assert all(not k.startswith(("nalezitosti", "navrh_1", "hodnoceni_1", "posouzeni_1")) for k, *_ in pis2.volani + hod2.volani)
def test_spotreba_ulozena_po_kazdem_kroku(tmp_path):  # po pádu v hodnoceni_2 má beh.stav.spotreba 4 položky
def test_hlaseni_prubehu(tmp_path):  # zachycené hlášky obsahují "[1/12]" a "Hodnocení 1" a "skóre"
```

- [ ] **Step 2: Run – expected FAIL**

- [ ] **Step 3: Implementuj `refiner/smycka.py`**

- [ ] **Step 4: Run – expected PASS**

- [ ] **Step 5: Checkpoint** – zpráva: `feat: refinement loop with stop conditions and resume`

---

### Task 9: Souhrnný přehled HTML

**Files:**
- Create: `refiner/vystup/prehled.py`, `refiner/vystup/sablony/prehled.html.j2`, `tests/test_prehled.py`

**Interfaces:**
- Consumes: `Beh`, `Konfigurace`, `najdi_placeholdery`, `podezrele_udaje`, `sestav_kriteria`, `format_skore`
- Produces: `vytvor_prehled(beh: Beh, konfigurace: Konfigurace) -> Path` – zapíše `prehled.html` jen ze stavu a dat běhu (funguje i pro přerušený běh a běh bez hodnocení)

Obsah šablony = design kap. 7, body 1–6, v tomto pořadí. Texty důvodů: `cil_splnen` → „Cíl splněn (skóre X,X ≥ 9,5)“, `limit_revizi` → „Vyčerpán limit N revizí“, `zadna_zmena` → „Hodnotitel nenavrhl nic, co by prošlo posouzením“. Přerušený běh: červený blok „Běh byl přerušen“ s `stav.chyba` a větou „Pokračovat lze spuštěním pokracovat.bat.“ Tabulka skóre: řádky = kritéria (A, B, pak C a Celkem), sloupce = hodnocení 1…n, buňka zbarvená (< 7 červená, 7–8,9 oranžová, ≥ 9 zelená). „K ověření“ = `tvrzeni_k_overeni` posledního hodnocení finální verze + `podezrele_udaje(finalni, poptavka + podklady)` seskupené podle druhu. Cena = součet `Spotreba` × `ceny_usd_za_milion` (model bez ceny → „cena neznámá“), označená „orientačně“. Jinja2 `Environment(autoescape=True)`; styl inline v `<style>`, bez JavaScriptu.

- [ ] **Step 1: Napiš failing testy**

```python
def test_prehled_dokonceneho_behu(tmp_path):
    # dokončený běh ze smyčky s falešnými modely ([7.0, 9.8]) + FINALNI_nabidka.md s "[DOPLNIT: sazba za MD]"
    html = vytvor_prehled(beh, konf).read_text(encoding="utf-8")
    assert "Cíl splněn" in html and "FINALNI_nabidka.docx" in html and "sazba za MD" in html
    assert "Hodnocení 1" in html and "Hodnocení 2" in html and "9,8" in html
def test_prehled_odkazy_na_soubory_kroku(tmp_path):  # href="04_hodnoceni_1.md" apod. pro každý zapsaný krok
def test_prehled_preruseneho_behu_bez_hodnoceni(tmp_path):
    # běh přerušený v kroku nalezitosti → obsahuje "Běh byl přerušen" a hlášku, nespadne
def test_prehled_escapuje_html_z_modelu(tmp_path):     # Review Focus 4
    # zdůvodnění kritéria = "<script>alert(1)</script>"
    assert "<script>alert" not in html and "&lt;script&gt;" in html
def test_prehled_cena_a_tokeny(tmp_path):  # 2× Spotreba(claude-opus-5-5, 1_000_000 vstup, 0 výstup) → "8,00" USD
def test_prehled_finalni_neni_posledni_vysvetli(tmp_path):  # finální 2 ze 4 → věta o vyšším skóre verze 2
```

- [ ] **Step 2: Run – expected FAIL**

- [ ] **Step 3: Implementuj**

- [ ] **Step 4: Run – expected PASS**

- [ ] **Step 5: Checkpoint** – zpráva: `feat: html run overview`

---

### Task 10: Aplikace – zahájení, obnovení, dokončení a chyby

**Files:**
- Create: `refiner/aplikace.py`, `tests/test_aplikace.py`

**Interfaces:**
- Consumes: všechny předchozí úkoly
- Produces (`refiner/aplikace.py`):
  - `zahaj_beh(koren: Path, vstup: Path, profil: str, ted: datetime) -> tuple[Beh, Zdroje]` – `Beh.novy(koren/"output", …)`; zkopíruje `nastaveni.yaml`, `profily/<profil>.yaml` (jako `profil.yaml`), `prompty/` a případný `<vstup>.kriteria.yaml` (jako `kriteria.yaml`) do `SLOZKA_KONFIGURACE`; zapíše krok `poptavka` (`poptavka.md`) a `data/podklady.md`; `Zdroje.prompty` ukazuje na zkopírované prompty
  - `obnov_beh(slozka: Path) -> tuple[Beh, Zdroje]` – vše načte z kopií ve složce běhu; běh ve stavu `dokoncen` → `ChybaVstupu("Běh … je už dokončený.")`
  - `najdi_posledni_beh(output: Path, stavy: set[str]) -> Path | None` – nejnovější podle `vytvoreno`
  - `dokonci(beh: Beh, zdroje: Zdroje, pisatel: Model, hodnotitel: Model, hlaseni: Callable[[str], None], sablona: Path | None) -> int` – návratové kódy 0 hotovo, 1 přerušeno

**Chování `dokonci`:**
- Úspěch: `spust_smycku`; `FINALNI_<profil_nazev>.md` = text finální verze; `exportuj_docx` do `FINALNI_<profil_nazev>.docx` (selhání exportu = varování v `beh`, ne pád); `beh.ukonci("dokoncen", duvod, finalni_verze=…)`; `vytvor_prehled`; hlášení s cestou k `prehled.html`; vrací 0.
- `ChybaModelu`: `surova_odpoved` → `data/surova_odpoved_<čas>.txt`; `beh.ukonci("prerusen", chyba=e.hlaska)`; `logging.exception` do logu; přehled; hlášení `e.hlaska` + cesta ke složce běhu + „Pokračovat: pokracovat.bat“; vrací 1.
- `KeyboardInterrupt`: totéž s chybou „Přerušeno uživatelem (Ctrl+C).“; vrací 1.
- Jiná výjimka: totéž s chybou „Neočekávaná chyba programu – podrobnosti v data/beh.log.“; vrací 1.
- Selhání `vytvor_prehled` v chybové cestě se jen zaloguje a nepřebije původní chybu.

- [ ] **Step 1: Napiš failing testy**

```python
def test_zahaj_beh_zkopiruje_konfiguraci_a_vstup(tmp_path, koren_repa):
    # kořen v tmp s kopií nastaveni.yaml, profily/, prompty/, input/poptavka.md
    beh, z = zahaj_beh(koren, koren/"input"/"poptavka.md", "nabidka", T)
    assert (beh.slozka/"01_poptavka.md").exists() and (beh.slozka/"data/konfigurace/prompty/navrh.md").exists()
    assert z.prompty == beh.slozka/"data/konfigurace/prompty"
def test_obnoveni_pouzije_kopii_konfigurace(tmp_path):  # po změně koren/nastaveni.yaml má obnovený běh původní hodnotu
def test_obnoveni_dokonceneho_behu_odmitne(tmp_path):
def test_dokonci_uspech(tmp_path):
    assert dokonci(beh, z, *skript([9.8]), hlaseni=out.append, sablona=None) == 0
    assert (beh.slozka/"FINALNI_nabidka.docx").exists() and (beh.slozka/"prehled.html").exists()
    assert Beh.otevri(beh.slozka).stav.stav == "dokoncen"
def test_chyba_api_ulozi_rozpracovany_beh(tmp_path):
    # hodnotitel vyhodí ChybaModelu("kredit", "OpenAI") v hodnoceni_1
    assert dokonci(...) == 1
    st = Beh.otevri(beh.slozka).stav
    assert st.stav == "prerusen" and "kredit" in st.chyba and (beh.slozka/"02_navrh_v1.md").exists()
    assert "pokracovat.bat" in "\n".join(out) and (beh.slozka/"prehled.html").exists()
def test_surova_odpoved_se_ulozi(tmp_path):  # ChybaModelu(..., surova_odpoved="{rozbite") → soubor v data/
def test_ctrl_c_ulozi_prerusen_beh(tmp_path):                          # Review Focus 5
    # pisatel vyhodí KeyboardInterrupt v navrh_1 → návrat 1, stav prerusen, chyba "Ctrl+C"; obnov_beh + dokonci doběhne
def test_neocekavana_vyjimka(tmp_path):    # ZeroDivisionError → 1, "Neočekávaná chyba", traceback v data/beh.log
def test_selhani_docx_exportu_je_varovani(tmp_path, monkeypatch):  # exportuj_docx vyhodí → 0, varování ve stavu
def test_najdi_posledni_preruseny(tmp_path):
```

- [ ] **Step 2: Run – expected FAIL**

- [ ] **Step 3: Implementuj** – logování: `logging.FileHandler(beh.slozka/"data"/"beh.log", encoding="utf-8")` připojený na dobu `dokonci`.

- [ ] **Step 4: Run – expected PASS**

- [ ] **Step 5: Checkpoint** – zpráva: `feat: run lifecycle with saved partial runs on errors`

---

### Task 11: Skuteční klienti Claude a GPT

**Files:**
- Create: `refiner/modely/claude.py`, `refiner/modely/gpt.py`, `tests/test_claude.py`, `tests/test_gpt.py`

**Interfaces:**
- Consumes: `Model`, `ChybaModelu`, `prevod_vyjimky` (Task 5), `NastaveniModelu` (Task 1), `Spotreba`
- Produces:
  - `class ClaudeModel(nastaveni: NastaveniModelu, klient: Any | None = None)` – `nazev` = model; výchozí klient `anthropic.Anthropic(max_retries=…, timeout=…)`
  - `class GptModel(nastaveni: NastaveniModelu, klient: Any | None = None)` – `nazev` = model; výchozí klient `openai.OpenAI(max_retries=…, timeout=…)`

**ClaudeModel:**
- Společné parametry: `model`, `system=[{"type": "text", "text": instrukce, "cache_control": {"type": "ephemeral"}}]`, `messages=[{"role": "user", "content": zadani}]`, `output_config={"effort": effort or nastaveni.claude.effort}`; při `fallback: true` navíc `betas=["server-side-fallback-2026-07-01"]`, `fallbacks="default"`. Parametr `thinking` neposílat (Opus 5.5 běží adaptivně).
- `json`: `klient.beta.messages.parse(..., max_tokens=max_tokens_json, output_format=schema)` → `response.parsed_output`.
- `text`: `with klient.beta.messages.stream(..., max_tokens=max_tokens_text) as s: msg = s.get_final_message()` → spojené `text` bloky.
- `stop_reason == "refusal"` → `ChybaModelu("odmitnuti", "Anthropic", detail=stop_details.category)`; `"max_tokens"` → `"uriznuto"`; `parsed_output is None` → `"nevalidni_vystup"` se surovým textem. Výjimky SDK → `prevod_vyjimky`. Spotřeba z `usage.input_tokens`, `usage.output_tokens`, `usage.cache_read_input_tokens or 0`.
- Ověř v nainstalovaném SDK (`inspect.signature(anthropic.Anthropic().beta.messages.parse)`), že `parse` přijme `output_config` s `effort` zároveň s `output_format` a že `stream`/`parse` přijmou `fallbacks`. Když ne, pošli dotčený parametr přes `extra_body` a zapiš to do komentáře u volání.

**GptModel:**
- `json`: `klient.responses.parse(model=…, instructions=instrukce, input=zadani, text_format=schema, reasoning={"effort": nastaveni.gpt.effort}, max_output_tokens=…)` → `response.output_parsed`.
- `text`: `klient.responses.create(...)` bez `text_format` → `response.output_text`.
- `response.status == "incomplete"` → `"uriznuto"` (detail `incomplete_details.reason`); položka obsahu `type == "refusal"` → `"odmitnuti"` (detail = text odmítnutí); `output_parsed is None` → `"nevalidni_vystup"`. Výjimky SDK → `prevod_vyjimky`. Spotřeba z `usage.input_tokens`, `usage.output_tokens`, `usage.input_tokens_details.cached_tokens`.
- Parametr `effort` z protokolu GptModel ignoruje.

- [ ] **Step 1: Napiš failing testy** – klient = ručně psaný falešný objekt (`SimpleNamespace` s metodami, které zaznamenají `kwargs` a vrátí připravenou odpověď); žádné síťové volání

```python
# test_claude.py
def test_json_posle_cache_effort_a_fallback():
    m.json("INSTR", "ZADANI", VystupNalezitosti, krok="nalezitosti", effort="medium")
    kw = klient.posledni_kwargs
    assert kw["model"] == "claude-opus-5-5" and kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kw["output_config"]["effort"] == "medium" and kw["fallbacks"] == "default" and "thinking" not in kw
def test_json_bez_fallbacku_kdyz_vypnuto():
def test_text_streamuje_a_spoji_bloky():         # dva text bloky → spojený text, max_tokens 64000
def test_uriznuti_a_odmitnuti():                 # stop_reason max_tokens → druh uriznuto; refusal → odmitnuti s kategorií
def test_vyjimka_sdk_prevedena():                # parse vyhodí anthropic.RateLimitError → ChybaModelu druh pretizeni
def test_spotreba():                             # usage 100/50/30 → Spotreba(krok, model, 100, 50, 30)
# test_gpt.py
def test_json_posle_reasoning_a_schema():        # reasoning == {"effort": "high"}, text_format is Hodnoceni, instructions == "INSTR"
def test_incomplete_je_uriznuto():
def test_refusal_je_odmitnuti():
def test_output_parsed_none_je_nevalidni():
def test_vyjimka_sdk_prevedena():                # openai.APIConnectionError → druh sit
def test_spotreba_s_cached_tokens():
```

- [ ] **Step 2: Run – expected FAIL**

- [ ] **Step 3: Implementuj** (včetně ověření signatur z popisu výše)

- [ ] **Step 4: Run – expected PASS**

- [ ] **Step 5: Checkpoint** – zpráva: `feat: Claude and GPT clients`

---

### Task 12: CLI, ukázkový režim, spouštěcí soubory a README

**Files:**
- Create: `refiner/cli.py`, `refiner/__main__.py`, `_priprava.bat`, `spustit.bat`, `pokracovat.bat`, `podklady.priklad/profil_firmy.md`, `tests/test_cli.py`
- Modify: `refiner/modely/falesne.py` (přidat `demo_modely`), `README.md` (přepsat pro konzultanta)

**Interfaces:**
- Consumes: `aplikace` (Task 10), klienti (Task 11), `najdi_vstupy`, `dostupne_profily`
- Produces:
  - `demo_modely() -> tuple[FalesnyModel, FalesnyModel]` – odpovědi jako `Callable`, fungují pro libovolnou poptávku: náležitosti = až 5 odrážkových řádků poptávky (citace = řádek), návrh = Markdown s nadpisy a `[DOPLNIT: …]`, skóre 7,5 → 8,5 → 9,0 → 9,3, část návrhů odmítnutá
  - `main(argv: list[str] | None = None, *, koren: Path | None = None, vstup_fn: Callable[[str], str] = input, vystup: TextIO | None = None, tovarna_modelu: Callable[[Konfigurace, bool], tuple[Model, Model]] | None = None) -> int`
  - Příkazy: `python -m refiner [--nanecisto]`; `python -m refiner --pokracovat [SLOZKA]` (bez hodnoty = poslední běh ve stavu `prerusen`/`bezi`). Podpříkaz `porovnat` přidá Task 13.
  - Návratové kódy: 0 hotovo, 1 běh přerušen, 2 chyba konfigurace/vstupu/uživatele (`ChybaKonfigurace`, `ChybaVstupu`, chybějící klíč, prázdný `input/`).

**Chování `main`:**
- Na začátku `vystup.reconfigure(encoding="utf-8", errors="replace")`, pokud to proud umí; všechny hlášky přes jednu funkci, která zapíše a zavolá `flush()`.
- `load_dotenv(koren/".env")`. Mimo `--nanecisto` před prvním voláním zkontroluje oba klíče; chybějící → `ChybaModelu("klic", <služba>).hlaska` + „Vzor najdete v souboru .env.example.“, návrat 2.
- Vstupy: žádný → „Ve složce input/ není žádná poptávka (DOCX, MD nebo TXT).“, 2; jeden → rovnou; víc → očíslovaný výběr (neplatná volba se zopakuje).
- Profily: víc než jeden → „Nabídka, nebo směrnice?“ jako očíslovaný výběr (názvy z `Profil.nazev`); jinak `vychozi_profil`.
- `sablona = koren/"podklady"/"sablona.docx"`, pokud existuje.
- Výchozí `tovarna_modelu`: `--nanecisto` → `demo_modely()`, jinak `(ClaudeModel(...), GptModel(...))`.

**Spouštěcí soubory** (všechny `@echo off`, `chcp 65001 >nul`, `cd /d "%~dp0"`):
- `_priprava.bat`: najde Python (`py -3`, jinak `python`); nenajde → „Nainstalujte Python 3.10 nebo novější z python.org (zaškrtněte ‚Add to PATH‘).“ a `exit /b 1`. Bez `.venv\Scripts\python.exe` vytvoří venv. Instaluje `requirements.txt`, jen když se liší od `.venv\requirements.nainstalovano` (`fc /b`), pak ho tam zkopíruje.
- `spustit.bat`: `call _priprava.bat || goto konec`, `.venv\Scripts\python.exe -m refiner %*`, `:konec`, `pause`.
- `pokracovat.bat`: totéž s `-m refiner --pokracovat %*`.

**README.md** (česky, pro konzultanta): první spuštění (Python, `.env` z `.env.example`), běžné použití (soubor do `input/`, dvojklik `spustit.bat`, otevřít `prehled.html`), profil firmy (`podklady/profil_firmy.md` ze šablony, volitelně `sablona.docx`), úprava kritérií (`profily/*.yaml`, `<poptavka>.kriteria.yaml`, `prompty/`), přerušený běh (`pokracovat.bat`), ukázka bez nákladů (`spustit.bat --nanecisto`), upozornění na data z designu kap. 13 a orientační cena běhu.

**`podklady.priklad/profil_firmy.md`:** šablona s oddíly Identifikace (obchodní firma, IČ, sídlo, plátce DPH), Sazby (cena za MD), Tým (role, jméno, praxe, certifikace), Reference (zakázka, rok, rozsah, kontakt/souhlas), Obchodní podmínky (platnost nabídky, splatnost) a větou „Co nevyplníte, nástroj ponechá v nabídce jako [DOPLNIT: …].“

- [ ] **Step 1: Napiš failing testy `tests/test_cli.py`** – kořen v `tmp_path` s kopií `nastaveni.yaml`, `profily/`, `prompty/` a `input/poptavka.md`

```python
def test_nanecisto_cely_beh(koren):
    assert main(["--nanecisto"], koren=koren, vstup_fn=lambda _: "1", vystup=io.StringIO()) == 0
    slozka = next((koren/"output").iterdir())
    assert (slozka/"prehled.html").exists() and (slozka/"FINALNI_nabidka.docx").exists()
def test_chybejici_klic(koren):
    out = io.StringIO(); assert main([], koren=koren, vstup_fn=..., vystup=out) == 2
    assert "ANTHROPIC_API_KEY" in out.getvalue() and ".env.example" in out.getvalue()
    assert not (koren/"output").exists() or not any((koren/"output").iterdir())
def test_prazdny_input(koren):                      # → 2, hláška o input/
def test_vyber_z_vice_souboru(koren):               # 2 soubory; vstup_fn vrací "9" pak "2" → zpracován druhý
def test_vyber_profilu(koren):                      # profily nabidka + smernice; odpověď "2" → beh.stav.profil == "smernice"
def test_chyba_konfigurace_je_kod_2(koren):         # rozbitý nastaveni.yaml → 2, hláška se jménem souboru
def test_pokracovat_bez_hodnoty_najde_posledni(koren):
    # tovarna: 1. běh selže v hodnoceni_1 (kód 1); --pokracovat s fungující továrnou → 0, stejná složka dokončena
def test_hlaseni_neshodi_cp1250_konzoli(koren):     # Review Focus 2
    buf = io.BytesIO(); konzole = io.TextIOWrapper(buf, encoding="cp1250", errors="strict")
    assert main(["--nanecisto"], koren=koren, vstup_fn=lambda _: "1", vystup=konzole) == 0
```

- [ ] **Step 2: Run – expected FAIL**

- [ ] **Step 3: Implementuj `cli.py`, `__main__.py`, `demo_modely`, `.bat`, šablonu profilu a README**

- [ ] **Step 4: Run – expected PASS** (`tests/test_cli.py` a celá sada `tests/`)

- [ ] **Step 5: Ruční ověření na Windows**

Smaž `.venv`, dvojklik na `spustit.bat` → vytvoří prostředí. S prázdným `.env` vypíše chybějící klíč a okno zůstane otevřené. Pak `spustit.bat --nanecisto` → v `output/` nová složka, `prehled.html` se otevře v prohlížeči a čeština se v konzoli zobrazuje správně. Výsledek popiš uživateli.

- [ ] **Step 6: Checkpoint** – zpráva: `feat: CLI, demo mode, Windows launchers and README`

---

### Task 13: Porovnání s referencí

**Files:**
- Create: `refiner/porovnani.py`, `refiner/vystup/sablony/porovnani.html.j2`, `prompty/porovnani_kriteria.md`, `prompty/porovnani_prvky.md`, `prompty/porovnani_pokryti.md`, `porovnat.bat`, `tests/test_porovnani.py`
- Modify: `refiner/cli.py` (podpříkaz `porovnat SLOZKA [--reference SOUBOR]`; bez `SLOZKA` = poslední dokončený běh), `refiner/aplikace.py` (nic, pokud stačí `obnov_beh`; jinak přidej `otevri_dokonceny(slozka) -> tuple[Beh, Zdroje]`), `README.md` (oddíl Porovnání)

**Interfaces:**
- Consumes: `ohodnot`, `spocitej`, `vykresli_prompt`, `Beh`, `Zdroje`, `Model`, `nacti_jako_markdown`
- Produces (`refiner/porovnani.py`, Pydantic schémata bez výchozích hodnot):
  - `SrovnaniKriteria(id: str, lepsi: Literal["A","B","stejne"], zduvodneni: str)`; `Srovnani(kriteria: list[SrovnaniKriteria])`
  - `PrvekReference(id: str, popis: str)`; `SeznamPrvku(prvky: list[PrvekReference])`
  - `PokrytiPrvku(id: str, stav: Literal["je","castecne","chybi"], komentar: str)`; `Pokryti(polozky: list[PokrytiPrvku])`
  - `VysledekPorovnani(skore_reference: VysledekSkore, skore_generovane: VysledekSkore, srovnani: dict[str, Literal["generovana","reference","nerozhodne"]], zduvodneni: dict[str, list[str]], prvky: list[PrvekReference], pokryti: list[PokrytiPrvku])`
  - `zkombinuj_srovnani(s1: Srovnani, s2: Srovnani) -> dict[str, Literal["generovana","reference","nerozhodne"]]` – v `s1` je A = generovaná, B = reference; v `s2` naopak; shoda → vítěz, rozpor nebo `stejne` → `nerozhodne`
  - `najdi_referenci(koren: Path) -> Path` – jediný podporovaný soubor v `examples/`; jinak `ChybaVstupu("…použijte --reference")`
  - `porovnej(beh: Beh, zdroje: Zdroje, reference_md: str, hodnotitel: Model, hlaseni: Callable[[str], None]) -> Path` – 5 volání hodnotitele (kroky `porovnani_kalibrace`, `porovnani_srovnani_1`, `porovnani_srovnani_2`, `porovnani_prvky`, `porovnani_pokryti`); zapíše `porovnani.html`, `porovnani_formular.md`, `data/porovnani.json`; běh musí být `dokoncen` (jinak `ChybaVstupu`)

Kalibrace = první prvek `ohodnot(hodnotitel, zdroje, kriteria, reference_md, [], krok="porovnani_kalibrace")`, kde `kriteria = sestav_kriteria(<náležitosti z běhu>, zdroje.konfigurace.kriteria_profilu)`; skóre přes `spocitej`. `skore_generovane` = uložené skóre finální verze z `beh.stav.skore`. `porovnani_prvky.md`: vypiš 15–40 konkrétních obsahových prvků reference (ne fakta o dodavateli). `porovnani_pokryti.md`: pro každý prvek stav v generované nabídce. `porovnani_kriteria.md`: pro každé kritérium, který z dokumentů A/B je lepší a proč; dokumenty označené jen A/B. `porovnani_formular.md` obsahuje přesně otázky z designu kap. 11 bod 4 s místem na odpověď. HTML: kalibrace nahoře s větou, zda reference dosáhla cílového skóre; pak srovnání po kritériích, tabulka pokrytí (chybějící první), odkaz na formulář; autoescape.

- [ ] **Step 1: Napiš failing testy**

```python
def test_zkombinuj_srovnani():
    s1 = Srovnani(kriteria=[k("B1","A"), k("B2","B"), k("B3","A"), k("B4","stejne")])
    s2 = Srovnani(kriteria=[k("B1","B"), k("B2","A"), k("B3","A"), k("B4","stejne")])
    assert zkombinuj_srovnani(s1, s2) == {"B1": "generovana", "B2": "reference", "B3": "nerozhodne", "B4": "nerozhodne"}
def test_porovnej_zapise_vystupy(tmp_path):  # dokončený běh z falešných modelů + falešný hodnotitel pro 5 kroků
    html = porovnej(beh, z, "# Reference", hod, print).read_text(encoding="utf-8")
    assert "Kalibrace" in html and (beh.slozka/"porovnani_formular.md").exists()
    assert [k for k, *_ in hod.volani] == ["porovnani_kalibrace", "porovnani_srovnani_1", "porovnani_srovnani_2", "porovnani_prvky", "porovnani_pokryti"]
def test_poradi_dokumentu_se_prohodi(tmp_path):  # zadání srovnani_1 má generovanou jako A, srovnani_2 jako B
def test_pisatel_nikdy_nevidi_referenci(tmp_path):  # celý běh + porovnání: "REFERENCNI-ZNACKA" není v žádném volání pisatele
def test_porovnani_nedokonceneho_behu(tmp_path): # → ChybaVstupu
def test_najdi_referenci(tmp_path):              # 1 soubor → cesta; 0 nebo 2 → ChybaVstupu s "--reference"
def test_cli_porovnat_bez_slozky(koren):         # poslední dokončený běh, továrna s falešným hodnotitelem → 0
```

- [ ] **Step 2: Run – expected FAIL**

- [ ] **Step 3: Implementuj** (`porovnat.bat` stejně jako `pokracovat.bat`, s `-m refiner porovnat %*`)

- [ ] **Step 4: Run – expected PASS** (celá sada `tests/`)

- [ ] **Step 5: Checkpoint** – zpráva: `feat: comparison with reference offer`

---

### Task 14: První ostrý běh a ladění (s uživatelem)

Úkol bez nového kódu na začátku. Volá placená API: **před krokem 2 požádej uživatele o souhlas** s náklady (odhad 3–6 USD za běh + menší částka za porovnání) a o vyplněný `.env`.

- [ ] **Step 1: Příprava** – požádej uživatele, aby vyplnil `podklady/profil_firmy.md` stejnými fakty, jaké obsahuje referenční nabídka (sazba, tým, reference), jinak srovnání v kapitolách cena/tým/reference nebude férové (design kap. 11).
- [ ] **Step 2: Ostrý běh** – `spustit.bat` na `input/Národní rozvojová banka.docx`. Expected: běh doběhne, `prehled.html` ukazuje důvod ukončení a skóre po kritériích.
- [ ] **Step 3: Porovnání** – `porovnat.bat`. Expected: `porovnani.html` s kalibrací reference.
- [ ] **Step 4: Rozbor s uživatelem** – shrň: skóre reference vs. generované nabídky (je 9,5 reálné?), chybějící prvky, podezřelé údaje a tvrzení k ověření, skutečnou cenu a dobu běhu. Požádej uživatele o vyplnění `porovnani_formular.md`.
- [ ] **Step 5: Ladění** – úpravy promptů, profilu nebo prahů navrhni uživateli jako konkrétní změny souborů. Prováděj je až po jeho souhlasu; každá úprava kódu jde přes test podle TDD.
- [ ] **Step 6: Checkpoint** – soubory změněné při ladění; zpráva: `tune: prompts and criteria after first real run`

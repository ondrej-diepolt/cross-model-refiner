"""Klient GPT přes `codex exec` (předplatné ChatGPT) implementující protokol Model."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TypeVar

import pydantic
from openai.lib._pydantic import to_strict_json_schema
from pydantic import BaseModel

from refiner.data import Spotreba
from refiner.konfigurace import NastaveniModelu
from refiner.modely import podproces
from refiner.modely.chyby import ChybaModelu, DruhChyby, chyba_parsovani, skryj_klice
from refiner.modely.podproces import Spoustec, VyprselCas, Vysledek

T = TypeVar("T", bound=BaseModel)

_log = logging.getLogger(__name__)
_SLUZBA = "Codex"
_LOGIN_TIMEOUT_S = 60
# Typy položek, které znamenají, že model sáhl na nástroje (nemělo by se stát; jen varování).
_NASTROJE = frozenset({"command_execution", "file_change", "mcp_tool_call", "web_search"})

_RE_LIMIT = re.compile(r"you['’]ve hit your usage limit[^\n]*|usage_limit_reached|quota_exceeded", re.I)
_RE_NEPRIHLASEN = re.compile(r"not signed in|codex login", re.I)
_RE_MODEL = re.compile(r"is not supported when using codex with a chatgpt account", re.I)
_RE_PRETIZENI = re.compile(r"rate_limit_exceeded|server_overloaded", re.I)


def druh_chyby_codex(text: str) -> DruhChyby | None:
    """Druh chyby podle textu, který vypíše Codex."""
    if _RE_LIMIT.search(text):
        return "limit_predplatneho"
    if _RE_NEPRIHLASEN.search(text):
        return "neprihlasen"
    if _RE_MODEL.search(text):
        return "model_nedostupny"
    if _RE_PRETIZENI.search(text):
        return "pretizeni"
    return None


def precti_udalosti(stdout: str) -> tuple[dict | None, list[str], set[str]]:
    """Z JSONL na stdout: (součet usage z `turn.completed` nebo None, zprávy z `turn.failed`
    a `error`, typy položek `item.*`). Řádky, které nejsou JSON objekt, se přeskočí."""
    usage: dict[str, int] | None = None
    zpravy: list[str] = []
    typy: set[str] = set()
    for radek in stdout.splitlines():
        try:
            ev = json.loads(radek)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        typ = ev.get("type")
        if typ == "turn.completed" and isinstance(ev.get("usage"), dict):
            usage = usage or {}
            for klic, hodnota in ev["usage"].items():
                if isinstance(hodnota, int):
                    usage[klic] = usage.get(klic, 0) + hodnota
        elif typ in ("turn.failed", "error"):
            chyba = ev.get("error")
            zprava = ev.get("message") or (chyba.get("message") if isinstance(chyba, dict) else None)
            if isinstance(zprava, str) and zprava:
                zpravy.append(zprava)
        elif isinstance(typ, str) and typ.startswith("item.") and isinstance(ev.get("item"), dict):
            if isinstance(ev["item"].get("type"), str):
                typy.add(ev["item"]["type"])
    return usage, zpravy, typy


class CodexModel:
    def __init__(self, nastaveni: NastaveniModelu, spust: Spoustec | None = None):
        self._n = nastaveni
        self._c = nastaveni.predplatne.codex
        self.nazev = self._c.model
        self._spust = spust or podproces.spust
        self._spotreba: list[Spotreba] = []
        program = podproces.najdi_program("codex", self._c.prikaz)
        if program is None:
            raise ChybaModelu("nenainstalovano", _SLUZBA)
        self._program = str(podproces.nativni_codex(program))
        self._zkontroluj_prihlaseni()

    # ------------------------------------------------------------ spuštění

    def _spust_nastroj(self, argv: list[str], stdin: str, cwd: Path, timeout_s: float) -> Vysledek:
        env = podproces.ciste_prostredi()
        try:
            return self._spust(argv, stdin, env, cwd, timeout_s)
        except VyprselCas as exc:
            raise ChybaModelu("timeout", _SLUZBA) from exc
        except FileNotFoundError as exc:
            raise ChybaModelu("nenainstalovano", _SLUZBA) from exc

    def _zkontroluj_prihlaseni(self) -> None:
        with podproces.docasne_adresare() as (prace, _):
            v = self._spust_nastroj([self._program, "login", "status"], "", prace, _LOGIN_TIMEOUT_S)
        text = (v.stdout + "\n" + v.stderr).strip()
        if v.kod != 0 or "Logged in using ChatGPT" not in text:
            prvni = text.splitlines()[0] if text else "bez výstupu"
            raise ChybaModelu("neprihlasen", _SLUZBA, detail=skryj_klice(prvni)[:200])

    def _volej(self, instrukce: str, zadani: str, krok: str, schema: type[BaseModel] | None) -> str | None:
        """Spustí `codex exec` a vrátí obsah výstupního souboru (None, když chybí nebo je prázdný)."""
        with podproces.docasne_adresare() as (prace, soubory):
            soubor_instrukce = soubory / "instrukce.md"
            soubor_instrukce.write_text(instrukce, encoding="utf-8")
            vystup = soubory / "odpoved.txt"
            c = self._c
            argv = [self._program, "exec", "--json", "--ephemeral", "--skip-git-repo-check",
                    "--ignore-user-config", "--ignore-rules",
                    "-s", "read-only", "-C", str(prace), "-m", c.model,
                    "-c", f"model_reasoning_effort={c.effort}", "-c", "model_reasoning_summary=none",
                    "-c", f"model_instructions_file={json.dumps(str(soubor_instrukce))}",
                    "-c", "approval_policy=never", "-c", "web_search=disabled",
                    "-c", "features.shell_tool=false", "-c", "project_doc_max_bytes=0",
                    "-c", "include_permissions_instructions=false", "-c", "include_environment_context=false",
                    "-c", "skills.include_instructions=false"]
            for funkce in ("plugins", "apps", "memories", "hooks", "image_generation", "browser_use",
                           "computer_use"):
                argv += ["--disable", funkce]
            argv += ["-o", str(vystup)]
            if schema is not None:
                soubor_schematu = soubory / "schema.json"
                soubor_schematu.write_text(json.dumps(to_strict_json_schema(schema)), encoding="utf-8")
                argv += ["--output-schema", str(soubor_schematu)]
            argv.append("-")
            _log.debug("codex argv: %s", argv)
            v = self._spust_nastroj(argv, zadani, prace, self._n.timeout_s)
            odpoved = vystup.read_text(encoding="utf-8", errors="replace") if vystup.is_file() else ""
        return self._vyhodnot(v, krok, odpoved)

    # ------------------------------------------------------------ vyhodnocení

    def _vyhodnot(self, v: Vysledek, krok: str, odpoved: str) -> str | None:
        usage, zpravy, typy = precti_udalosti(v.stdout)
        if usage is not None:
            self._spotreba.append(Spotreba(
                krok=krok, model=self.nazev, vstup=usage.get("input_tokens", 0),
                vystup=usage.get("output_tokens", 0), cache_cteni=usage.get("cached_input_tokens", 0),
                predplatne=True))
        for typ in sorted(typy & _NASTROJE):
            _log.warning("Codex použil nástroj (%s), ač mají být vypnuté (krok %s)", typ, krok)
        if v.kod != 0 or (zpravy and not odpoved.strip()):
            raise self._chyba("\n".join([*zpravy, v.stderr]).strip(), v.kod)
        return odpoved if odpoved.strip() else None

    def _chyba(self, text: str, kod: int) -> ChybaModelu:
        if "context_window_exceeded" in text:
            return ChybaModelu("jina", _SLUZBA, detail="Zadání je pro model příliš dlouhé (context_window_exceeded).")
        druh = druh_chyby_codex(text)
        if druh == "limit_predplatneho":
            nalez = _RE_LIMIT.search(text)
            return ChybaModelu(druh, _SLUZBA, detail=skryj_klice(nalez.group(0).strip())[:200])
        if druh == "model_nedostupny":
            return ChybaModelu(druh, _SLUZBA, detail=self.nazev)
        if druh is not None:
            return ChybaModelu(druh, _SLUZBA, detail=skryj_klice(text)[:500])
        return ChybaModelu("jina", _SLUZBA, detail=skryj_klice(text)[:500] or f"kód ukončení {kod}")

    # ------------------------------------------------------------ protokol Model

    def json(self, instrukce: str, zadani: str, schema: type[T], *, krok: str,
             effort: str | None = None) -> T:
        odpoved = self._volej(instrukce, zadani, krok, schema)
        if odpoved is None:
            raise ChybaModelu("nevalidni_vystup", _SLUZBA, detail="chybí výstupní soubor nebo je prázdný")
        try:
            return schema.model_validate_json(odpoved)
        except pydantic.ValidationError as exc:
            raise chyba_parsovani(exc, _SLUZBA) from exc

    def text(self, instrukce: str, zadani: str, *, krok: str) -> str:
        odpoved = self._volej(instrukce, zadani, krok, None)
        if odpoved is None:
            raise ChybaModelu("jina", _SLUZBA, detail="Codex nevrátil žádnou odpověď")
        return odpoved

    def vyzvedni_spotrebu(self) -> list[Spotreba]:
        spotreba, self._spotreba = self._spotreba, []
        return spotreba

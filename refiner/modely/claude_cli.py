"""Klient Claude přes `claude -p` (předplatné Max) implementující protokol Model."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, TypeVar

import pydantic
from pydantic import BaseModel

from refiner.data import Spotreba
from refiner.konfigurace import NastaveniModelu
from refiner.modely import podproces
from refiner.modely.chyby import ChybaModelu, DruhChyby, chyba_parsovani, skryj_klice
from refiner.modely.podproces import Spoustec, VyprselCas, Vysledek

T = TypeVar("T", bound=BaseModel)

_log = logging.getLogger(__name__)
_SLUZBA = "Claude Code"

# Pojistky navíc k --safe-mode: do volání se nesmí dostat CLAUDE.md, přílohy ani git instrukce.
_NAVIC = {"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1", "CLAUDE_CODE_DISABLE_ATTACHMENTS": "1",
          "CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS": "1"}
_AUTH_TIMEOUT_S = 60

_RE_NEPRIHLASEN = re.compile(r"not logged in|login expired|failed to authenticate|please run /login", re.I)
_RE_LIMIT = re.compile(r"you['’]ve hit your[^\n]*|usage limit[^\n]*|(?:session|weekly|opus) limit[^\n]*", re.I)
_RE_MODEL = re.compile(r"is not available with the claude|not a recognized model|model[^\n]{0,80}not found"
                       r"|not_found_error", re.I)
_RE_PRETIZENI = re.compile(r"\(429\)|\b429\b|temporarily limiting|overloaded|\b529\b", re.I)
_RE_SIT = re.compile(r"api_error|econn(?:reset|refused)|enotfound|etimedout|fetch failed|network error"
                     r"|unable to connect", re.I)


def druh_chyby_claude(text: str) -> DruhChyby | None:
    """Druh chyby podle textu, který vypíše Claude Code (bez `uriznuto` a `sit`)."""
    if _RE_NEPRIHLASEN.search(text):
        return "neprihlasen"
    if _RE_LIMIT.search(text):
        return "limit_predplatneho"
    if _RE_MODEL.search(text):
        return "model_nedostupny"
    if _RE_PRETIZENI.search(text):
        return "pretizeni"
    return None


def _objekt(text: str) -> dict | None:
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


class ClaudeCliModel:
    def __init__(self, nastaveni: NastaveniModelu, spust: Spoustec | None = None):
        self._n = nastaveni
        self._c = nastaveni.predplatne.claude
        self.nazev = self._c.model
        self._spust = spust or podproces.spust
        self._spotreba: list[Spotreba] = []
        program = podproces.najdi_program("claude", self._c.prikaz)
        if program is None:
            raise ChybaModelu("nenainstalovano", _SLUZBA)
        self._program = str(program)
        self._zkontroluj_prihlaseni()

    # ------------------------------------------------------------ spuštění

    def _spust_nastroj(self, argv: list[str], stdin: str, cwd: Path, timeout_s: float) -> Vysledek:
        env = podproces.ciste_prostredi(navic=_NAVIC)
        try:
            return self._spust(argv, stdin, env, cwd, timeout_s)
        except VyprselCas as exc:
            raise ChybaModelu("timeout", _SLUZBA) from exc
        except FileNotFoundError as exc:
            raise ChybaModelu("nenainstalovano", _SLUZBA) from exc

    def _zkontroluj_prihlaseni(self) -> None:
        with podproces.docasne_adresare() as (prace, _):
            v = self._spust_nastroj([self._program, "auth", "status"], "", prace, _AUTH_TIMEOUT_S)
        stav = _objekt(v.stdout)
        if stav is None:
            raise ChybaModelu("neprihlasen", _SLUZBA,
                              detail=skryj_klice((v.stdout + v.stderr).strip())[:200] or "nečitelný výstup")
        if stav.get("loggedIn") is not True or stav.get("authMethod") != "claude.ai":
            raise ChybaModelu("neprihlasen", _SLUZBA, detail=f"authMethod={stav.get('authMethod')}")

    def _volej(self, instrukce: str, zadani: str, krok: str, effort: str,
               schema: type[BaseModel] | None) -> dict[str, Any]:
        with podproces.docasne_adresare() as (prace, soubory):
            soubor = soubory / "instrukce.md"
            soubor.write_text(instrukce, encoding="utf-8")
            argv = [self._program, "-p", "--output-format", "json", "--no-session-persistence",
                    "--model", self._c.model, "--effort", effort,
                    "--system-prompt-file", str(soubor),
                    "--tools", "", "--disallowedTools", "mcp__*", "--strict-mcp-config",
                    "--safe-mode", "--permission-prompts", "none"]
            if schema is not None:
                argv += ["--json-schema", json.dumps(schema.model_json_schema())]
            _log.debug("claude argv: %s", argv)
            v = self._spust_nastroj(argv, zadani, prace, self._n.timeout_s)
        return self._vyhodnot(v, krok)

    # ------------------------------------------------------------ vyhodnocení

    def _vyhodnot(self, v: Vysledek, krok: str) -> dict[str, Any]:
        odp = _objekt(v.stdout)
        if odp is None:
            raise self._chyba(v.stdout + "\n" + v.stderr)
        u = odp.get("usage")
        if isinstance(u, dict):
            self._spotreba.append(Spotreba(
                krok=krok, model=self.nazev, vstup=u.get("input_tokens") or 0,
                vystup=u.get("output_tokens") or 0, cache_cteni=u.get("cache_read_input_tokens") or 0,
                cache_zapis=u.get("cache_creation_input_tokens") or 0, predplatne=True))
        if odp.get("is_error") or v.kod != 0:
            if odp.get("subtype") == "error_max_structured_output_retries":
                raise ChybaModelu("nevalidni_vystup", _SLUZBA, detail="vyčerpané pokusy o strukturovaný výstup")
            chyby = odp.get("errors")
            text = "\n".join(str(x) for x in (odp.get("result"), *(chyby if isinstance(chyby, list) else []),
                                              v.stderr) if x)
            raise self._chyba(text)
        if odp.get("stop_reason") == "max_tokens":
            raise ChybaModelu("uriznuto", _SLUZBA)
        if odp.get("stop_reason") == "refusal":
            raise ChybaModelu("odmitnuti", _SLUZBA, detail="nespecifikováno")
        return odp

    def _chyba(self, text: str) -> ChybaModelu:
        druh = druh_chyby_claude(text)
        if druh == "limit_predplatneho":
            nalez = _RE_LIMIT.search(text)
            return ChybaModelu(druh, _SLUZBA, detail=skryj_klice(nalez.group(0).strip())[:200])
        if druh == "model_nedostupny":
            return ChybaModelu(druh, _SLUZBA, detail=self.nazev)
        if druh is not None:
            return ChybaModelu(druh, _SLUZBA, detail=skryj_klice(text.strip())[:500])
        if _RE_SIT.search(text):
            return ChybaModelu("sit", _SLUZBA, detail=skryj_klice(text.strip())[:500])
        return ChybaModelu("jina", _SLUZBA, detail=skryj_klice(text.strip())[:500])

    # ------------------------------------------------------------ protokol Model

    def json(self, instrukce: str, zadani: str, schema: type[T], *, krok: str,
             effort: str | None = None) -> T:
        odp = self._volej(instrukce, zadani, krok, effort or self._c.effort, schema)
        vystup = odp.get("structured_output")
        if vystup is None:
            raise ChybaModelu("nevalidni_vystup", _SLUZBA, detail="chybí structured_output",
                              surova_odpoved=str(odp.get("result") or ""))
        try:
            return schema.model_validate(vystup)
        except pydantic.ValidationError as exc:
            raise chyba_parsovani(exc, _SLUZBA) from exc

    def text(self, instrukce: str, zadani: str, *, krok: str) -> str:
        odp = self._volej(instrukce, zadani, krok, self._c.effort, None)
        vysledek = odp.get("result")
        if not isinstance(vysledek, str):
            raise ChybaModelu("jina", _SLUZBA, detail="odpověď neobsahuje result")
        return vysledek

    def vyzvedni_spotrebu(self) -> list[Spotreba]:
        spotreba, self._spotreba = self._spotreba, []
        return spotreba

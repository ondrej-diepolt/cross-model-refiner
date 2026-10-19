"""GPT client via `codex exec` (ChatGPT subscription), implementing the Model protocol."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TypeVar

import pydantic
from openai.lib._pydantic import to_strict_json_schema
from pydantic import BaseModel

from refiner.data import TokenUsage
from refiner.configuration import ModelSettings
from refiner.models import subprocess
from refiner.models.errors import ModelError, ErrorKind, parsing_error, redact_keys
from refiner.models.subprocess import Runner, ProcessTimeout, ProcessResult

T = TypeVar("T", bound=BaseModel)

_log = logging.getLogger(__name__)
_SERVICE = "Codex"
_LOGIN_TIMEOUT_S = 60
# Item types indicating tool use (unexpected, but reported only as a warning).
_TOOLS = frozenset({"command_execution", "file_change", "mcp_tool_call", "web_search"})

_RE_LIMIT = re.compile(r"you['’]ve hit your usage limit[^\n]*|usage_limit_reached|quota_exceeded", re.I)
_RE_UNAUTHENTICATED = re.compile(r"not signed in|codex login", re.I)
_RE_MODEL = re.compile(r"is not supported when using codex with a chatgpt account", re.I)
_RE_OVERLOADED = re.compile(r"rate_limit_exceeded|server_overloaded", re.I)


def codex_error_kind(text: str) -> ErrorKind | None:
    """Classify error text emitted by Codex."""
    if _RE_LIMIT.search(text):
        return 'subscription_limit'
    if _RE_UNAUTHENTICATED.search(text):
        return 'not_authenticated'
    if _RE_MODEL.search(text):
        return 'model_unavailable'
    if _RE_OVERLOADED.search(text):
        return 'overloaded'
    return None


def read_events(stdout: str) -> tuple[dict | None, list[str], set[str]]:
    """Read stdout JSONL: (summed turn.completed usage or None, turn.failed/error messages,
    item.* types). Skip lines that are not JSON objects."""
    usage: dict[str, int] | None = None
    messages: list[str] = []
    types: set[str] = set()
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        type_ = ev.get("type")
        if type_ == "turn.completed" and isinstance(ev.get("usage"), dict):
            usage = usage or {}
            for key, value in ev["usage"].items():
                if isinstance(value, int):
                    usage[key] = usage.get(key, 0) + value
        elif type_ in ("turn.failed", "error"):
            error = ev.get("error")
            message = ev.get("message") or (error.get("message") if isinstance(error, dict) else None)
            if isinstance(message, str) and message:
                messages.append(message)
        elif isinstance(type_, str) and type_.startswith("item.") and isinstance(ev.get("item"), dict):
            if isinstance(ev["item"].get("type"), str):
                types.add(ev["item"]["type"])
    return usage, messages, types


class CodexModel:
    def __init__(self, settings: ModelSettings, run: Runner | None = None):
        self._n = settings
        self._c = settings.subscription.codex
        self.name = self._c.model
        self._run = run or subprocess.run
        self._usage: list[TokenUsage] = []
        program = subprocess.find_program("codex", self._c.command)
        if program is None:
            raise ModelError('not_installed', _SERVICE)
        self._program = str(subprocess.native_codex(program))
        self._check_login()

    # ------------------------------------------------------------ execution

    def _run_tool(self, argv: list[str], stdin: str, cwd: Path, timeout_s: float) -> ProcessResult:
        env = subprocess.clean_environment()
        try:
            return self._run(argv, stdin, env, cwd, timeout_s)
        except ProcessTimeout as exc:
            raise ModelError('timeout', _SERVICE) from exc
        except FileNotFoundError as exc:
            raise ModelError('not_installed', _SERVICE) from exc

    def _check_login(self) -> None:
        with subprocess.temporary_directories() as (work, _):
            v = self._run_tool([self._program, "login", "status"], "", work, _LOGIN_TIMEOUT_S)
        text = (v.stdout + "\n" + v.stderr).strip()
        if v.returncode != 0 or "Logged in using ChatGPT" not in text:
            first = text.splitlines()[0] if text else "bez výstupu"
            raise ModelError('not_authenticated', _SERVICE, detail=redact_keys(first)[:200])

    def _call(self, instructions: str, task: str, step: str, schema: type[BaseModel] | None) -> str | None:
        """Run `codex exec` and return output-file text, or None when missing or empty."""
        with subprocess.temporary_directories() as (work, files):
            instructions_file = files / 'instructions.md'
            instructions_file.write_text(instructions, encoding="utf-8")
            output = files / 'response.txt'
            c = self._c
            argv = [self._program, "exec", "--json", "--ephemeral", "--skip-git-repo-check",
                    "--ignore-user-config", "--ignore-rules",
                    "-s", "read-only", "-C", str(work), "-m", c.model,
                    "-c", f"model_reasoning_effort={c.effort}", "-c", "model_reasoning_summary=none",
                    "-c", f"model_instructions_file={json.dumps(str(instructions_file))}",
                    "-c", "approval_policy=never", "-c", "web_search=disabled",
                    "-c", "features.shell_tool=false", "-c", "project_doc_max_bytes=0",
                    "-c", "include_permissions_instructions=false", "-c", "include_environment_context=false",
                    "-c", "skills.include_instructions=false"]
            for feature in ("plugins", "apps", "memories", "hooks", "image_generation", "browser_use",
                           "computer_use"):
                argv += ["--disable", feature]
            argv += ["-o", str(output)]
            if schema is not None:
                schema_file = files / "schema.json"
                schema_file.write_text(json.dumps(to_strict_json_schema(schema)), encoding="utf-8")
                argv += ["--output-schema", str(schema_file)]
            argv.append("-")
            _log.debug("codex argv: %s", argv)
            v = self._run_tool(argv, task, work, self._n.timeout_s)
            response = output.read_text(encoding="utf-8", errors="replace") if output.is_file() else ""
        return self._evaluate(v, step, response)

    # ------------------------------------------------------------ response handling

    def _evaluate(self, v: ProcessResult, step: str, response: str) -> str | None:
        usage, messages, types = read_events(v.stdout)
        if usage is not None:
            self._usage.append(TokenUsage(
                step=step, model=self.name, input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0), cache_read_tokens=usage.get("cached_input_tokens", 0),
                subscription=True))
        for type_ in sorted(types & _TOOLS):
            _log.warning("Codex used a tool (%s) despite tools being disabled (step %s)", type_, step)
        if v.returncode != 0 or (messages and not response.strip()):
            raise self._error("\n".join([*messages, v.stderr]).strip(), v.returncode)
        return response if response.strip() else None

    def _error(self, text: str, returncode: int) -> ModelError:
        if "context_window_exceeded" in text:
            return ModelError('other', _SERVICE, detail="Zadání je pro model příliš dlouhé (context_window_exceeded).")
        kind = codex_error_kind(text)
        if kind == 'subscription_limit':
            match = _RE_LIMIT.search(text)
            return ModelError(kind, _SERVICE, detail=redact_keys(match.group(0).strip())[:200])
        if kind == 'model_unavailable':
            return ModelError(kind, _SERVICE, detail=self.name)
        if kind is not None:
            return ModelError(kind, _SERVICE, detail=redact_keys(text)[:500])
        return ModelError('other', _SERVICE, detail=redact_keys(text)[:500] or f"kód ukončení {returncode}")

    # ------------------------------------------------------------ Model protocol

    def json(self, instructions: str, task: str, schema: type[T], *, step: str,
             effort: str | None = None) -> T:
        response = self._call(instructions, task, step, schema)
        if response is None:
            raise ModelError('invalid_output', _SERVICE, detail="chybí výstupní soubor nebo je prázdný")
        try:
            return schema.model_validate_json(response)
        except pydantic.ValidationError as exc:
            raise parsing_error(exc, _SERVICE) from exc

    def text(self, instructions: str, task: str, *, step: str) -> str:
        response = self._call(instructions, task, step, None)
        if response is None:
            raise ModelError('other', _SERVICE, detail="Codex nevrátil žádnou odpověď")
        return response

    def take_usage(self) -> list[TokenUsage]:
        usage, self._usage = self._usage, []
        return usage

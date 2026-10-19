"""Claude client via `claude -p` (Max subscription), implementing the Model protocol."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, TypeVar

import pydantic
from pydantic import BaseModel

from refiner.data import TokenUsage
from refiner.configuration import ModelSettings
from refiner.models import subprocess
from refiner.models.errors import ModelError, ErrorKind, parsing_error, redact_keys
from refiner.models.subprocess import Runner, ProcessTimeout, ProcessResult

T = TypeVar("T", bound=BaseModel)

_log = logging.getLogger(__name__)
_SERVICE = "Claude Code"

# Extra --safe-mode isolation: exclude CLAUDE.md, attachments, and Git instructions.
_EXTRA = {"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1", "CLAUDE_CODE_DISABLE_ATTACHMENTS": "1",
          "CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS": "1"}
_AUTH_TIMEOUT_S = 60

_RE_UNAUTHENTICATED = re.compile(r"not logged in|login expired|failed to authenticate|please run /login", re.I)
_RE_LIMIT = re.compile(r"you['’]ve hit your[^\n]*|usage limit[^\n]*|(?:session|weekly|opus) limit[^\n]*", re.I)
_RE_MODEL = re.compile(r"is not available with the claude|not a recognized model|model[^\n]{0,80}not found"
                       r"|not_found_error", re.I)
_RE_OVERLOADED = re.compile(r"\(429\)|\b429\b|temporarily limiting|overloaded|\b529\b", re.I)
_RE_NETWORK = re.compile(r"api_error|econn(?:reset|refused)|enotfound|etimedout|fetch failed|network error"
                     r"|unable to connect", re.I)


def claude_error_kind(text: str) -> ErrorKind | None:
    """Classify Claude Code error text, excluding truncation and network errors."""
    if _RE_UNAUTHENTICATED.search(text):
        return 'not_authenticated'
    if _RE_LIMIT.search(text):
        return 'subscription_limit'
    if _RE_MODEL.search(text):
        return 'model_unavailable'
    if _RE_OVERLOADED.search(text):
        return 'overloaded'
    return None


def _object(text: str) -> dict | None:
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


class ClaudeCliModel:
    def __init__(self, settings: ModelSettings, run: Runner | None = None):
        self._n = settings
        self._c = settings.subscription.claude
        self.name = self._c.model
        self._run = run or subprocess.run
        self._usage: list[TokenUsage] = []
        program = subprocess.find_program("claude", self._c.command)
        if program is None:
            raise ModelError('not_installed', _SERVICE)
        self._program = str(program)
        self._check_login()

    # ------------------------------------------------------------ execution

    def _run_tool(self, argv: list[str], stdin: str, cwd: Path, timeout_s: float) -> ProcessResult:
        env = subprocess.clean_environment(extra=_EXTRA)
        try:
            return self._run(argv, stdin, env, cwd, timeout_s)
        except ProcessTimeout as exc:
            raise ModelError('timeout', _SERVICE) from exc
        except FileNotFoundError as exc:
            raise ModelError('not_installed', _SERVICE) from exc

    def _check_login(self) -> None:
        with subprocess.temporary_directories() as (work, _):
            v = self._run_tool([self._program, "auth", "status"], "", work, _AUTH_TIMEOUT_S)
        status = _object(v.stdout)
        if status is None:
            raise ModelError('not_authenticated', _SERVICE,
                              detail=redact_keys((v.stdout + v.stderr).strip())[:200] or "nečitelný výstup")
        if status.get("loggedIn") is not True or status.get("authMethod") != "claude.ai":
            raise ModelError('not_authenticated', _SERVICE, detail=f"authMethod={status.get('authMethod')}")

    def _call(self, instructions: str, task: str, step: str, effort: str,
               schema: type[BaseModel] | None) -> dict[str, Any]:
        with subprocess.temporary_directories() as (work, files):
            file = files / 'instructions.md'
            file.write_text(instructions, encoding="utf-8")
            argv = [self._program, "-p", "--output-format", "json", "--no-session-persistence",
                    "--model", self._c.model, "--effort", effort,
                    "--system-prompt-file", str(file),
                    "--tools", "", "--disallowedTools", "mcp__*", "--strict-mcp-config",
                    "--safe-mode", "--permission-prompts", "none"]
            if schema is not None:
                argv += ["--json-schema", json.dumps(schema.model_json_schema())]
            _log.debug("claude argv: %s", argv)
            v = self._run_tool(argv, task, work, self._n.timeout_s)
        return self._evaluate(v, step)

    # ------------------------------------------------------------ response handling

    def _evaluate(self, v: ProcessResult, step: str) -> dict[str, Any]:
        response = _object(v.stdout)
        if response is None:
            raise self._error(v.stdout + "\n" + v.stderr)
        u = response.get("usage")
        if isinstance(u, dict):
            self._usage.append(TokenUsage(
                step=step, model=self.name, input_tokens=u.get("input_tokens") or 0,
                output_tokens=u.get("output_tokens") or 0, cache_read_tokens=u.get("cache_read_input_tokens") or 0,
                cache_write_tokens=u.get("cache_creation_input_tokens") or 0, subscription=True))
        if response.get("is_error") or v.returncode != 0:
            if response.get("subtype") == "error_max_structured_output_retries":
                raise ModelError('invalid_output', _SERVICE, detail="vyčerpané pokusy o strukturovaný výstup")
            errors = response.get("errors")
            text = "\n".join(str(x) for x in (response.get("result"), *(errors if isinstance(errors, list) else []),
                                              v.stderr) if x)
            raise self._error(text)
        if response.get("stop_reason") == "max_tokens":
            raise ModelError('truncated', _SERVICE)
        if response.get("stop_reason") == "refusal":
            raise ModelError('refused', _SERVICE, detail="nespecifikováno")
        return response

    def _error(self, text: str) -> ModelError:
        kind = claude_error_kind(text)
        if kind == 'subscription_limit':
            match = _RE_LIMIT.search(text)
            return ModelError(kind, _SERVICE, detail=redact_keys(match.group(0).strip())[:200])
        if kind == 'model_unavailable':
            return ModelError(kind, _SERVICE, detail=self.name)
        if kind is not None:
            return ModelError(kind, _SERVICE, detail=redact_keys(text.strip())[:500])
        if _RE_NETWORK.search(text):
            return ModelError('network', _SERVICE, detail=redact_keys(text.strip())[:500])
        return ModelError('other', _SERVICE, detail=redact_keys(text.strip())[:500])

    # ------------------------------------------------------------ Model protocol

    def json(self, instructions: str, task: str, schema: type[T], *, step: str,
             effort: str | None = None) -> T:
        response = self._call(instructions, task, step, effort or self._c.effort, schema)
        output = response.get("structured_output")
        if output is None:
            raise ModelError('invalid_output', _SERVICE, detail="chybí structured_output",
                              raw_response=str(response.get("result") or ""))
        try:
            return schema.model_validate(output)
        except pydantic.ValidationError as exc:
            raise parsing_error(exc, _SERVICE) from exc

    def text(self, instructions: str, task: str, *, step: str) -> str:
        response = self._call(instructions, task, step, self._c.effort, None)
        result = response.get("result")
        if not isinstance(result, str):
            raise ModelError('other', _SERVICE, detail="odpověď neobsahuje result")
        return result

    def take_usage(self) -> list[TokenUsage]:
        usage, self._usage = self._usage, []
        return usage

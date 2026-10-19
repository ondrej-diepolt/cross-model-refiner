"""Shared CLI adapter support (Claude Code, Codex): credential-free environments,
program discovery, execution with stdin and timeouts, and temporary directories."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


class ProcessTimeout(Exception):
    """The subprocess timed out and its entire process tree was terminated."""


Runner = Callable[[list[str], str, dict[str, str], Path, float], ProcessResult]
#          (argv, stdin, env, cwd, timeout_s)

# Variables supplying API credentials or non-subscription authentication, or overriding
# the model, effort, or service endpoint. Remove these for both CLI tools.
REMOVE: tuple[str, ...] = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL",
    "ANTHROPIC_PROFILE", "ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_ORGANIZATION_ID",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_SIMPLE", "CLAUDE_CODE_EFFORT_LEVEL", "CLAUDECODE",
    "OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "OPENAI_BASE_URL",
    "OPENAI_FEDERATION_RULE_ID", "OPENAI_IDENTITY_TOKEN_FILE",
)
# Also remove matching prefixes: nested Claude Code sessions and any additional
# ANTHROPIC_* / OPENAI_* credentials. Keep CLAUDE_CONFIG_DIR and CODEX_HOME, which
# locate subscription authentication.
_PREFIXES = ("CLAUDE_CODE_", "ANTHROPIC_", "OPENAI_")

_REMOVE_UPPER = frozenset(n.upper() for n in REMOVE)
_TREE_STOP_TIMEOUT_S = 10.0


def clean_environment(source: Mapping[str, str] | None = None,
                    extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Copy the environment without keys or authentication variables, ignoring case."""
    source = os.environ if source is None else source
    extra = extra or {}
    forbidden = [k for k in extra if k.upper() in _REMOVE_UPPER]
    if forbidden:
        raise ValueError(f"Do prostředí podprocesu nelze přidat: {', '.join(forbidden)}")
    env = {k: v for k, v in source.items()
           if k.upper() not in _REMOVE_UPPER and not k.upper().startswith(_PREFIXES)}
    env.update(extra)
    return env


class _Job:
    """Windows Job Object: kill descendants whose parent has exited, which taskkill /T misses."""

    def __init__(self) -> None:
        self._handle = None
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.CreateJobObjectW.restype = wintypes.HANDLE
            k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
            k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
            k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
            k32.CloseHandle.argtypes = [wintypes.HANDLE]

            class _BasicLimits(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                            ("SchedulingClass", wintypes.DWORD)]

            class _Io(ctypes.Structure):
                _fields_ = [(n, ctypes.c_uint64) for n in (
                    "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                    "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

            class _ExtendedLimits(ctypes.Structure):
                _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", _Io),
                            ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

            handle = k32.CreateJobObjectW(None, None)
            if not handle:
                return
            info = _ExtendedLimits()
            info.BasicLimitInformation.LimitFlags = 0x2000   # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not k32.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
                k32.CloseHandle(handle)
                return
            self._k32, self._handle = k32, handle
        except (OSError, AttributeError, ImportError):
            self._handle = None

    def add(self, proc: subprocess.Popen) -> None:
        if self._handle is not None:
            self._k32.AssignProcessToJobObject(self._handle, int(proc._handle))  # type: ignore[attr-defined]

    def kill(self) -> None:
        if self._handle is not None:
            self._k32.TerminateJobObject(self._handle, 1)

    def close(self) -> None:
        """Closing the handle terminates remaining descendants (KILL_ON_JOB_CLOSE)."""
        if self._handle is not None:
            self._k32.CloseHandle(self._handle)
            self._handle = None


def _kill_tree(proc: subprocess.Popen, job: _Job) -> None:
    if sys.platform == "win32":
        job.kill()
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           capture_output=True, timeout=_TREE_STOP_TIMEOUT_S, check=False, env=clean_environment())
        except (OSError, subprocess.SubprocessError):
            pass
        proc.kill()
    else:
        import signal
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()


def run_process(argv: list[str], stdin: str, env: dict[str, str], cwd: Path,
                 timeout_s: float) -> ProcessResult:
    """Run a program with UTF-8 stdin; terminate its entire process tree on timeout.

    Use a file for stdin: writing to a pipe could block beyond the timeout when the child
    does not read it. A Windows Job Object tracks both parents and descendants.
    """
    job = _Job()
    with tempfile.TemporaryFile() as input_file:
        input_file.write(stdin.encode("utf-8"))
        input_file.seek(0)
        proc = subprocess.Popen(
            argv, stdin=input_file, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=cwd, env=env, start_new_session=(sys.platform != "win32"))
        try:
            job.add(proc)
            try:
                out, err = proc.communicate(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                _kill_tree(proc, job)
                try:
                    proc.communicate(timeout=_TREE_STOP_TIMEOUT_S)
                except subprocess.TimeoutExpired:
                    pass   # reader threads are daemons; closing pipes would block on them
                raise ProcessTimeout() from None
        finally:
            job.close()
    return ProcessResult(proc.returncode, out.decode("utf-8", errors="replace"),
                    err.decode("utf-8", errors="replace"))


run: Runner = run_process  # adapters capture subprocess.run in constructors; conftest replaces it


def find_program(default: str, configured: str | None) -> Path | None:
    """Prefer a configured path or PATH name; otherwise use the default name from PATH."""
    if configured:
        path = Path(configured)
        if path.is_file():
            return path
        found = shutil.which(configured)
    else:
        found = shutil.which(default)
    return Path(found) if found else None


_NATIVE_CODEX = Path("node_modules/@openai/codex/node_modules/@openai/codex-win32-x64"
                      "/vendor/x86_64-pc-windows-msvc/bin/codex.exe")


def native_codex(path: Path) -> Path:
    """Replace the npm codex.cmd launcher with native codex.exe to avoid cmd.exe character limits."""
    if path.suffix.lower() == ".cmd":
        native = path.parent / _NATIVE_CODEX
        if native.is_file():
            return native
    return path


@contextmanager
def temporary_directories() -> Iterator[tuple[Path, Path]]:
    """Yield (work, files): an empty working directory and a directory for prompts, schemas, and output."""
    with tempfile.TemporaryDirectory(prefix="refiner-", ignore_cleanup_errors=True) as root:
        work = Path(root) / 'work'
        files = Path(root) / 'files'
        work.mkdir()
        files.mkdir()
        yield work, files

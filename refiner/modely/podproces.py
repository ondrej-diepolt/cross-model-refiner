"""Společný základ adaptérů nad CLI nástroji (Claude Code, Codex): prostředí bez klíčů,
nalezení programu, spuštění se stdin a timeoutem, dočasné adresáře."""
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
class Vysledek:
    kod: int
    stdout: str
    stderr: str


class VyprselCas(Exception):
    """Podproces nedoběhl v časovém limitu (celý jeho strom procesů byl zabit)."""


Spoustec = Callable[[list[str], str, dict[str, str], Path, float], Vysledek]
#          (argv, stdin, env, cwd, timeout_s)

# Proměnné, které by nástroji dodaly API klíč nebo jiné ověření než předplatné, případně
# změnily model, effort či cílovou službu. Odstraňují se pro oba nástroje najednou.
ODSTRANIT: tuple[str, ...] = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL",
    "ANTHROPIC_PROFILE", "ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_ORGANIZATION_ID",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_SIMPLE", "CLAUDE_CODE_EFFORT_LEVEL", "CLAUDECODE",
    "OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "OPENAI_BASE_URL",
    "OPENAI_FEDERATION_RULE_ID", "OPENAI_IDENTITY_TOKEN_FILE",
)
# Navíc se odstraní vše s těmito předponami (vnořená relace Claude Code a jakákoli další
# proměnná ANTHROPIC_* / OPENAI_*, která by mohla nést přihlášení). CLAUDE_CONFIG_DIR
# a CODEX_HOME zůstávají: určují, kde leží přihlášení předplatným.
_PREDPONY = ("CLAUDE_CODE_", "ANTHROPIC_", "OPENAI_")

_ODSTRANIT_VELKE = frozenset(n.upper() for n in ODSTRANIT)
_KONEC_STROMU_S = 10.0


def ciste_prostredi(zdroj: Mapping[str, str] | None = None,
                    navic: Mapping[str, str] | None = None) -> dict[str, str]:
    """Kopie prostředí bez klíčů a přihlašovacích proměnných (bez ohledu na velikost písmen)."""
    zdroj = os.environ if zdroj is None else zdroj
    navic = navic or {}
    zakazane = [k for k in navic if k.upper() in _ODSTRANIT_VELKE]
    if zakazane:
        raise ValueError(f"Do prostředí podprocesu nelze přidat: {', '.join(zakazane)}")
    env = {k: v for k, v in zdroj.items()
           if k.upper() not in _ODSTRANIT_VELKE and not k.upper().startswith(_PREDPONY)}
    env.update(navic)
    return env


class _Job:
    """Windows Job Object: zabije i potomky, jejichž rodič už skončil (taskkill /T je nenajde)."""

    def __init__(self) -> None:
        self._uchyt = None
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

            class _Zakladni(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                            ("SchedulingClass", wintypes.DWORD)]

            class _Io(ctypes.Structure):
                _fields_ = [(n, ctypes.c_uint64) for n in (
                    "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                    "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

            class _Rozsirene(ctypes.Structure):
                _fields_ = [("BasicLimitInformation", _Zakladni), ("IoInfo", _Io),
                            ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

            uchyt = k32.CreateJobObjectW(None, None)
            if not uchyt:
                return
            info = _Rozsirene()
            info.BasicLimitInformation.LimitFlags = 0x2000   # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not k32.SetInformationJobObject(uchyt, 9, ctypes.byref(info), ctypes.sizeof(info)):
                k32.CloseHandle(uchyt)
                return
            self._k32, self._uchyt = k32, uchyt
        except (OSError, AttributeError, ImportError):
            self._uchyt = None

    def pridej(self, proc: subprocess.Popen) -> None:
        if self._uchyt is not None:
            self._k32.AssignProcessToJobObject(self._uchyt, int(proc._handle))  # type: ignore[attr-defined]

    def zabij(self) -> None:
        if self._uchyt is not None:
            self._k32.TerminateJobObject(self._uchyt, 1)

    def zavri(self) -> None:
        """Zavření uchytu zabije případné zbylé potomky (KILL_ON_JOB_CLOSE)."""
        if self._uchyt is not None:
            self._k32.CloseHandle(self._uchyt)
            self._uchyt = None


def _zabij_strom(proc: subprocess.Popen, job: _Job) -> None:
    if sys.platform == "win32":
        job.zabij()
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           capture_output=True, timeout=_KONEC_STROMU_S, check=False, env=ciste_prostredi())
        except (OSError, subprocess.SubprocessError):
            pass
        proc.kill()
    else:
        import signal
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()


def spust_proces(argv: list[str], stdin: str, env: dict[str, str], cwd: Path,
                 timeout_s: float) -> Vysledek:
    """Spustí program, prompt pošle přes stdin (UTF-8); po vypršení limitu zabije celý strom.

    Stdin jde ze souboru, ne z roury: zápis do roury by u procesu, který stdin nečte, blokoval
    mimo časový limit. Rodiče i potomky hlídá na Windows Job Object.
    """
    job = _Job()
    with tempfile.TemporaryFile() as vstup:
        vstup.write(stdin.encode("utf-8"))
        vstup.seek(0)
        proc = subprocess.Popen(
            argv, stdin=vstup, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=cwd, env=env, start_new_session=(sys.platform != "win32"))
        try:
            job.pridej(proc)
            try:
                out, err = proc.communicate(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                _zabij_strom(proc, job)
                try:
                    proc.communicate(timeout=_KONEC_STROMU_S)
                except subprocess.TimeoutExpired:
                    pass   # čtecí vlákna jsou daemon; roury nezavíráme (close() by čekal na ně)
                raise VyprselCas() from None
        finally:
            job.zavri()
    return Vysledek(proc.returncode, out.decode("utf-8", errors="replace"),
                    err.decode("utf-8", errors="replace"))


spust: Spoustec = spust_proces  # adaptéry berou `podproces.spust` v konstruktoru; conftest ho nahrazuje


def najdi_program(vychozi: str, nastaveny: str | None) -> Path | None:
    """Přednost má nastavená cesta (nebo název v PATH), jinak výchozí název v PATH."""
    if nastaveny:
        cesta = Path(nastaveny)
        if cesta.is_file():
            return cesta
        nalezeno = shutil.which(nastaveny)
    else:
        nalezeno = shutil.which(vychozi)
    return Path(nalezeno) if nalezeno else None


_NATIVNI_CODEX = Path("node_modules/@openai/codex/node_modules/@openai/codex-win32-x64"
                      "/vendor/x86_64-pc-windows-msvc/bin/codex.exe")


def nativni_codex(cesta: Path) -> Path:
    """npm spouštěč codex.cmd jde přes cmd.exe (limit 8191 znaků); použije se nativní codex.exe."""
    if cesta.suffix.lower() == ".cmd":
        nativni = cesta.parent / _NATIVNI_CODEX
        if nativni.is_file():
            return nativni
    return cesta


@contextmanager
def docasne_adresare() -> Iterator[tuple[Path, Path]]:
    """(prace, soubory): prázdný pracovní adresář podprocesu a adresář na prompt, schéma a výstup."""
    with tempfile.TemporaryDirectory(prefix="refiner-", ignore_cleanup_errors=True) as koren:
        prace = Path(koren) / "prace"
        soubory = Path(koren) / "soubory"
        prace.mkdir()
        soubory.mkdir()
        yield prace, soubory

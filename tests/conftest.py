import socket
import shutil
from pathlib import Path

import pytest

from refiner.models import subprocess


def _forbid_cli(*args, **kwargs):
    raise RuntimeError("Test attempted to invoke a real provider CLI")


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    def _forbid_network(*args, **kwargs):
        raise RuntimeError("Test attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", _forbid_network)
    monkeypatch.setattr(subprocess, "run", _forbid_cli)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture
def koren_repa() -> Path:
    return Path(__file__).parent.parent


@pytest.fixture
def zdroje(koren_repa):
    from tests.pomocne import zdroje_test

    return zdroje_test(koren_repa)


@pytest.fixture
def legacy_interrupted(tmp_path: Path) -> Path:
    source = Path(__file__).parent / "fixtures" / "legacy" / "interrupted"
    return Path(shutil.copytree(source, tmp_path / "legacy-interrupted"))


@pytest.fixture
def legacy_completed(tmp_path: Path) -> Path:
    source = Path(__file__).parent / "fixtures" / "legacy" / "completed"
    return Path(shutil.copytree(source, tmp_path / "legacy-completed"))

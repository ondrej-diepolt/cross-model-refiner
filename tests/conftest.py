import socket
import shutil
from pathlib import Path

import pytest

from refiner.modely import podproces


def _zakaz_nastroj(*args, **kwargs):
    raise RuntimeError("Test se pokusil spustit skutečný nástroj CLI")


@pytest.fixture(autouse=True)
def _bez_site(monkeypatch):
    def _zakaz(*args, **kwargs):
        raise RuntimeError("Test se pokusil o síťové spojení")

    monkeypatch.setattr(socket.socket, "connect", _zakaz)
    monkeypatch.setattr(podproces, "spust", _zakaz_nastroj)
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

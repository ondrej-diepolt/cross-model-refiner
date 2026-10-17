import socket
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _bez_site(monkeypatch):
    def _zakaz(*args, **kwargs):
        raise RuntimeError("Test se pokusil o síťové spojení")

    monkeypatch.setattr(socket.socket, "connect", _zakaz)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture
def koren_repa() -> Path:
    return Path(__file__).parent.parent

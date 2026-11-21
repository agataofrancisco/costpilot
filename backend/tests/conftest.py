from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.fakes.fake_openai import FakeOpenAIServer, start_fake_openai_server


@pytest.fixture
def fake_openai() -> Iterator[FakeOpenAIServer]:
    server = start_fake_openai_server()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def redis_url() -> str:
    """URL de um Redis real. Sem variável definida, os testes `-m redis` são ignorados."""
    url = os.environ.get("COSTPILOT_TEST_REDIS_URL")
    if not url:
        pytest.skip("COSTPILOT_TEST_REDIS_URL não definido (sem Redis real disponível)")
    return url


@pytest.fixture
def repo_config_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "config"


@pytest.fixture
def fake_closed_port_url() -> str:
    """URL de uma porta local que acabou de ser libertada: ligações são recusadas."""
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}/v1"

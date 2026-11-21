"""Configurações e apps de teste isolados (BD SQLite em tmp, relógio fixo e clientes)."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from app.auth.clients import hash_key
from app.config import REPO_ROOT, Settings
from app.container import Container, build_container
from app.main import create_app
from fastapi.testclient import TestClient

FIXED_NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

# Chaves de TESTE (nunca usadas fora dos testes). Cada uma mapeia para um principal fixo.
TEST_CLIENTS: list[dict[str, str]] = [
    {
        "name": "suporte",
        "key": "chave-teste-suporte",
        "tenant_id": "orbita-tech",
        "team": "suporte",
    },
    {"name": "dados", "key": "chave-teste-dados", "tenant_id": "orbita-tech", "team": "dados"},
    {"name": "bench", "key": "chave-teste-bench", "tenant_id": "orbita-tech", "team": "bench"},
    {
        "name": "marketing",
        "key": "chave-teste-marketing",
        "tenant_id": "orbita-tech",
        "team": "marketing",
    },
    {
        "name": "cliente-a",
        "key": "chave-teste-cliente-a",
        "tenant_id": "cliente-a",
        "team": "suporte",
    },
    {
        "name": "cliente-b",
        "key": "chave-teste-cliente-b",
        "tenant_id": "cliente-b",
        "team": "suporte",
    },
]
AUTH: dict[str, dict[str, str]] = {
    c["name"]: {"Authorization": f"Bearer {c['key']}"} for c in TEST_CLIENTS
}


def mock_model(
    model_id: str,
    *,
    quality: dict[str, float] | None = None,
    prior: dict[str, float] | None = None,
    allow_sensitive: bool = True,
    json_honest: bool = True,
    failure_rate: float = 0.0,
    latency_ms: float = 100.0,
    reports_usage: bool = True,
) -> dict[str, Any]:
    return {
        "id": model_id,
        "provider": "mock",
        "context_window": 32000,
        "supports_json_mode": True,
        "supports_tools": True,
        "typical_latency_ms": latency_ms,
        "allow_sensitive": allow_sensitive,
        "enabled": True,
        "prior_success": prior or {},
        "mock": {
            "quality": quality or {},
            "failure_rate": failure_rate,
            "latency_ms": latency_ms,
            "json_mode_honest": json_honest,
            "reports_usage": reports_usage,
        },
    }


def price_row(model_id: str, price_in: str, price_out: str) -> dict[str, Any]:
    return {
        "model": model_id,
        "input_per_mtok": float(price_in),
        "output_per_mtok": float(price_out),
        "effective_date": "2026-01-01",
        "source": "teste",
    }


def write_config(
    directory: Path,
    *,
    models: list[dict[str, Any]],
    prices: list[dict[str, Any]],
    teams: dict[str, dict[str, Any]],
    clients: list[dict[str, str]] | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO_ROOT / "config" / "policy.yaml", directory / "policy.yaml")
    (directory / "models.yaml").write_text(yaml.safe_dump({"models": models}), encoding="utf-8")
    (directory / "prices.yaml").write_text(
        yaml.safe_dump({"currency": "USD", "prices": prices}), encoding="utf-8"
    )
    (directory / "teams.yaml").write_text(yaml.safe_dump({"teams": teams}), encoding="utf-8")
    entries = [
        {
            "name": c["name"],
            "tenant_id": c["tenant_id"],
            "team": c["team"],
            "key_sha256": hash_key(c["key"]),
        }
        for c in (clients if clients is not None else TEST_CLIENTS)
    ]
    (directory / "clients.yaml").write_text(yaml.safe_dump({"clients": entries}), encoding="utf-8")
    return directory


def team(budget_usd: str = "5", fixed: str = "mock-mid", autopilot: bool = True) -> dict[str, Any]:
    return {"budget_usd": float(budget_usd), "fixed_model": fixed, "autopilot_default": autopilot}


def build_test_app(
    tmp_path: Path,
    *,
    models: list[dict[str, Any]],
    prices: list[dict[str, Any]],
    teams: dict[str, dict[str, Any]],
    adapters: dict[str, Any] | None = None,
    allow_override: bool = False,
    admin_token: str | None = "token-de-teste",
) -> tuple[TestClient, Container, Any]:
    """O cliente de teste envia por omissão a chave da equipa `suporte` (Authorization)."""
    config_dir = write_config(tmp_path / "config", models=models, prices=prices, teams=teams)
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{(tmp_path / 'costpilot-test.db').as_posix()}",
        config_dir=config_dir,
        admin_token=admin_token,
        allow_policy_override=allow_override,
        probe_on_startup=False,
        mock_seed=7,
        provider_timeout_seconds=5,
        reservation_ttl_seconds=60,
    )
    container = build_container(settings, adapters=adapters, clock=lambda: FIXED_NOW)
    app = create_app(settings, container)
    client = TestClient(app)
    client.headers.update(AUTH["suporte"])
    return client, container, app


def standard_setup() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Três modelos mock com perfis conhecidos. Preços iguais aos de config/prices.yaml."""
    models = [
        mock_model(
            "mock-cheap",
            quality={"classification": 0.9, "json_extraction": 1.0, "doc_qa": 0.9},
            prior={
                "classification": 0.9,
                "json_extraction": 0.8,
                "doc_qa": 0.9,
                "multi_step_reasoning": 0.6,
            },
        ),
        mock_model(
            "mock-mid",
            quality={"classification": 1.0, "json_extraction": 1.0, "doc_qa": 1.0},
            prior={
                "classification": 0.95,
                "json_extraction": 0.9,
                "doc_qa": 0.9,
                "multi_step_reasoning": 0.75,
            },
        ),
        mock_model(
            "mock-strong",
            quality={
                "classification": 1.0,
                "json_extraction": 1.0,
                "doc_qa": 1.0,
                "multi_step_reasoning": 1.0,
            },
            prior={
                "classification": 0.98,
                "json_extraction": 0.97,
                "doc_qa": 0.96,
                "multi_step_reasoning": 0.95,
            },
        ),
    ]
    prices = [
        price_row("mock-cheap", "0.10", "0.40"),
        price_row("mock-mid", "0.50", "1.50"),
        price_row("mock-strong", "3.00", "15.00"),
    ]
    return models, prices

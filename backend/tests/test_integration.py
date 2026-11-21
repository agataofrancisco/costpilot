"""Integração (6.2): preço desactualizado, model mismatch, multi-tenant e provider indisponível."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings
from app.container import build_container
from app.main import create_app
from app.providers.base import ChatRequest, ChatResponse, Usage
from fastapi.testclient import TestClient

from tests.support import AUTH, build_test_app, standard_setup, team
from tests.test_execute import classification_body, mock_adapter


class MismatchAdapter:
    """Responde com um modelo diferente do pedido: o registo tem de assinalar `model_mismatch`."""

    name = "mock"

    async def chat(self, request: ChatRequest):
        return ChatResponse(
            model=request.model,
            provider="mock",
            text="positivo",
            usage=Usage(input_tokens=5, output_tokens=2, reported=True),
            latency_ms=10.0,
            reported_model="modelo-diferente",
        )


def test_stale_price_is_refused_instead_of_using_a_guess(tmp_path: Path):
    """Pedido com data anterior à primeira linha de preço: não há preço em vigor -> sem modelo."""
    models, prices = standard_setup()
    config_dir = tmp_path / "config"
    from tests.support import write_config

    write_config(config_dir, models=models, prices=prices, teams={"suporte": team("5")})
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
        config_dir=config_dir,
        admin_token="t",
        probe_on_startup=False,
        provider_timeout_seconds=5,
        reservation_ttl_seconds=60,
    )
    past = datetime(2025, 6, 1, tzinfo=UTC)
    container = build_container(
        settings, adapters={"mock": mock_adapter(models)}, clock=lambda: past
    )
    client = TestClient(create_app(settings, container))

    response = client.post(
        "/route",
        json={"task_type": "classification", "input_tokens": 10},
        headers=AUTH["suporte"],
    )

    assert response.status_code == 422
    assert response.json()["code"] == "no_eligible_model"
    assert any("pricing_missing" in c for c in response.json()["conflicts"])


def test_model_mismatch_is_flagged_in_the_usage_ledger(tmp_path: Path):
    models, prices = standard_setup()
    client, container, _ = build_test_app(
        tmp_path,
        models=models,
        prices=prices,
        teams={"suporte": team("5")},
        adapters={"mock": MismatchAdapter()},
    )

    response = client.post("/execute", json=classification_body())

    assert response.status_code == 200
    rows = container.usage.recent(5)
    assert rows[0]["model"] == response.json()["model"]
    assert container.usage.aggregate()  # o registo existe
    from app.accounting.tables import UsageRecord
    from sqlalchemy import select

    with container.usage._sessions() as session:
        flags = session.execute(select(UsageRecord.model_mismatch)).scalars().all()
    assert any(flags)


def test_same_request_in_two_tenants_never_shares_cache(tmp_path: Path):
    models, prices = standard_setup()
    client, _, _ = build_test_app(
        tmp_path,
        models=models,
        prices=prices,
        teams={"suporte": team("5")},
        adapters={"mock": mock_adapter(models)},
    )
    # Mesmo pedido, chaves de tenants diferentes (mesma equipa): a identidade vem da chave.
    body = classification_body(cache=True, temperature=0)

    client.post("/execute", json=body, headers=AUTH["cliente-a"])
    second = client.post("/execute", json=body, headers=AUTH["cliente-b"])

    assert second.json()["cache"] == "miss"


def test_provider_outage_on_one_model_falls_back_to_next_in_chain(tmp_path: Path):
    """Um provider em baixo com escalonamento: a cadeia continua e o custo da falha é zero."""
    models, prices = standard_setup()

    class FlakyCheap:
        name = "mock"

        def __init__(self, inner):
            self.inner = inner

        async def chat(self, request):
            if request.model == "mock-cheap":
                from app.providers.base import FailureKind, ProviderFailure

                return ProviderFailure(FailureKind.UNAVAILABLE, "indisponível")
            return await self.inner.chat(request)

    client, container, _ = build_test_app(
        tmp_path,
        models=models,
        prices=prices,
        teams={"suporte": team("5")},
        adapters={"mock": FlakyCheap(mock_adapter(models))},
    )

    response = client.post("/execute", json=classification_body())

    assert response.status_code == 200
    body = response.json()
    assert [a["status"] for a in body["attempts"]][0] == "provider_error"
    assert body["attempts"][0]["cost_usd"] == "0.000000"
    assert body["model"] != "mock-cheap"

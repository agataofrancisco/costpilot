"""Execução ponta-a-ponta pela API (TestClient), com providers mock controlados."""

from __future__ import annotations

import asyncio
from decimal import Decimal

import httpx
from app.providers.base import ChatRequest
from app.providers.mock import MockAdapter, MockProfile
from app.providers.modelmesh import build_modelmesh_adapter

from tests.support import build_test_app, price_row, standard_setup, team

ORACLE_ANSWERS = {
    "json_extraction": '{"nome": "Ana"}',
    "classification": "positivo",
    "doc_qa": "Segundo manual-cap3#regras, a regra aplica-se.",
    "multi_step_reasoning": "FINAL: 42",
}


def oracle(request: ChatRequest) -> str | None:
    return ORACLE_ANSWERS.get(request.task_type)


def mock_adapter(models: list[dict]) -> MockAdapter:
    profiles = {
        m["id"]: MockProfile(
            quality=m["mock"]["quality"],
            failure_rate=m["mock"]["failure_rate"],
            latency_ms=m["mock"]["latency_ms"],
            json_mode_honest=m["mock"]["json_mode_honest"],
            reports_usage=m["mock"]["reports_usage"],
        )
        for m in models
        if m.get("mock") is not None
    }
    return MockAdapter(profiles, seed=7, oracle=oracle)


class SpyAdapter:
    """Envolve o mock e conta chamadas: prova que /route nunca chama um provider."""

    name = "mock"

    def __init__(self, inner: MockAdapter) -> None:
        self.inner = inner
        self.calls = 0

    async def chat(self, request: ChatRequest):
        self.calls += 1
        return await self.inner.chat(request)


def json_body(**overrides) -> dict:
    body = {
        "task": {
            "task_type": "json_extraction",
            "input_tokens": 10,
            "requires_json": True,
            "team": "suporte",
        },
        "messages": [{"role": "user", "content": "extrai o nome"}],
        "max_output_tokens": 128,
        "validation": {"required_fields": {"nome": "string"}},
    }
    body.update(overrides)
    return body


def classification_body(team_name: str = "suporte", **overrides) -> dict:
    body = {
        "task": {"task_type": "classification", "input_tokens": 10, "team": team_name},
        "messages": [{"role": "user", "content": "classifica o sentimento"}],
        "max_output_tokens": 16,
        "validation": {"labels": ["positivo", "negativo", "neutro"]},
    }
    body.update(overrides)
    return body


def _json_invalid_models() -> list[dict]:
    models, prices = standard_setup()
    models[0]["mock"]["quality"]["json_extraction"] = 0.0  # barato: JSON válido, campo errado
    return models


def test_invalid_json_escalates_and_both_attempts_are_counted(tmp_path):
    models = _json_invalid_models()
    _, prices = standard_setup()
    client, container, _ = build_test_app(
        tmp_path,
        models=models,
        prices=prices,
        teams={"suporte": team("5")},
        adapters={"mock": mock_adapter(models)},
    )

    response = client.post("/execute", json=json_body())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["resolved"] is True
    assert body["model"] == "mock-mid"
    assert body["decision"]["chosen"] == "mock-cheap"
    assert [a["status"] for a in body["attempts"]] == ["validation_failed", "ok"]
    assert [a["model"] for a in body["attempts"]] == ["mock-cheap", "mock-mid"]
    assert [a["reason"] for a in body["attempts"]] == ["autopilot", "escalation"]
    total = sum(Decimal(a["cost_usd"]) for a in body["attempts"])
    assert Decimal(body["total_cost_usd"]) == total
    # O orçamento regista exactamente o custo das duas tentativas.
    assert container.budget.snapshot("suporte").spent_micro == sum(
        int(round(Decimal(a["cost_usd"]) * 1_000_000)) for a in body["attempts"]
    )


def test_escalation_without_budget_returns_budget_exceeded_with_spent_cost(tmp_path):
    models = _json_invalid_models()
    _, prices = standard_setup()
    # 150 micro-USD: cabe a reserva do barato (53), mas não a do seguinte (197) depois de gastar 4.
    client, _, _ = build_test_app(
        tmp_path,
        models=models,
        prices=prices,
        teams={"suporte": team("0.00015")},
        adapters={"mock": mock_adapter(models)},
    )

    response = client.post("/execute", json=json_body())

    assert response.status_code == 402
    body = response.json()
    assert body["code"] == "budget_exceeded"
    assert body["spent_usd"] == "0.000004"
    assert len(body["attempts"]) == 1
    assert body["attempts"][0]["status"] == "validation_failed"


def test_first_attempt_is_refused_before_any_provider_call(tmp_path):
    models, prices = standard_setup()
    spy = SpyAdapter(mock_adapter(models))
    client, _, _ = build_test_app(
        tmp_path,
        models=models,
        prices=prices,
        # 5 micro-USD: a reserva do barato (16 tokens de saída) é 8 micro-USD, por isso recusa.
        teams={"suporte": team("0.000005")},
        adapters={"mock": spy},
    )

    response = client.post("/execute", json=classification_body())

    assert response.status_code == 402
    assert response.json()["code"] == "budget_exceeded"
    assert spy.calls == 0


def test_modelmesh_outage_returns_503_and_charges_nothing(tmp_path, fake_closed_port_url):
    models, prices = standard_setup()
    mm = {
        "id": "mm-model",
        "provider": "modelmesh",
        "context_window": 32000,
        "supports_json_mode": True,
        "supports_tools": False,
        "typical_latency_ms": 100,
        "allow_sensitive": True,
        "enabled": True,
        "prior_success": {"classification": 0.99},
    }
    prices.append(price_row("mm-model", "0.10", "0.40"))
    adapters = {
        "mock": mock_adapter(models),
        "modelmesh": build_modelmesh_adapter(fake_closed_port_url, "chave-virtual", 2),
    }
    client, container, _ = build_test_app(
        tmp_path,
        models=models + [mm],
        prices=prices,
        teams={"suporte": team("5", fixed="mm-model", autopilot=False)},
        adapters=adapters,
    )

    response = client.post("/execute", json=classification_body())

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "upstream_unavailable"
    assert [a["status"] for a in body["attempts"]] == ["provider_error"]
    assert body["attempts"][0]["failure_kind"] == "unavailable"
    assert body["attempts"][0]["cost_usd"] == "0.000000"
    assert container.budget.snapshot("suporte").spent_micro == 0


def test_cache_hit_is_marked_and_costs_nothing(tmp_path):
    models, prices = standard_setup()
    client, container, _ = build_test_app(
        tmp_path,
        models=models,
        prices=prices,
        teams={"suporte": team("5")},
        adapters={"mock": mock_adapter(models)},
    )
    body = classification_body(cache=True, temperature=0)

    first = client.post("/execute", json=body)
    spent_after_first = container.budget.snapshot("suporte").spent_micro
    second = client.post("/execute", json=body)

    assert first.json()["cache"] == "miss"
    assert second.headers.get("x-modelmesh-cache") == "hit"
    assert second.json()["cache"] == "hit"
    assert second.json()["total_cost_usd"] == "0.000000"
    assert second.json()["attempts"] == []
    assert container.budget.snapshot("suporte").spent_micro == spent_after_first


def test_cache_never_crosses_teams(tmp_path):
    models, prices = standard_setup()
    client, _, _ = build_test_app(
        tmp_path,
        models=models,
        prices=prices,
        teams={"suporte": team("5"), "dados": team("5", fixed="mock-cheap")},
        adapters={"mock": mock_adapter(models)},
    )
    suporte = client.post(
        "/execute", json=classification_body("suporte", cache=True, temperature=0)
    )
    dados = client.post("/execute", json=classification_body("dados", cache=True, temperature=0))

    assert suporte.json()["cache"] == "miss"
    assert dados.json()["cache"] == "miss"
    assert "x-modelmesh-cache" not in dados.headers


def test_non_zero_temperature_is_never_cached(tmp_path):
    models, prices = standard_setup()
    client, _, _ = build_test_app(
        tmp_path,
        models=models,
        prices=prices,
        teams={"suporte": team("5")},
        adapters={"mock": mock_adapter(models)},
    )
    body = classification_body(cache=True, temperature=0.7)

    first = client.post("/execute", json=body)
    second = client.post("/execute", json=body)

    assert first.json()["cache"] == "not_eligible"
    assert second.json()["cache"] == "not_eligible"
    assert "x-modelmesh-cache" not in second.headers


def test_high_sensitivity_never_reaches_unauthorized_model(tmp_path):
    models, prices = standard_setup()
    models[0]["allow_sensitive"] = False  # o barato não pode receber dados sensíveis
    client, _, _ = build_test_app(
        tmp_path,
        models=models,
        prices=prices,
        teams={"suporte": team("5")},
        adapters={"mock": mock_adapter(models)},
    )

    response = client.post(
        "/execute",
        json=classification_body(
            task={
                "task_type": "classification",
                "input_tokens": 10,
                "team": "suporte",
                "sensitivity": "high",
            }
        ),
    )

    assert response.status_code == 200
    assert response.json()["model"] != "mock-cheap"
    cheap = next(c for c in response.json()["decision"]["candidates"] if c["model"] == "mock-cheap")
    assert cheap["reasons"] == ["not_authorized_sensitive"]


def test_autopilot_switch_per_team_uses_fixed_model(tmp_path):
    models, prices = standard_setup()
    client, _, _ = build_test_app(
        tmp_path,
        models=models,
        prices=prices,
        teams={"suporte": team("5", fixed="mock-strong")},
        adapters={"mock": mock_adapter(models)},
    )
    headers = {"x-admin-token": "token-de-teste"}

    switch = client.put("/admin/teams/suporte/autopilot", json={"enabled": False}, headers=headers)
    response = client.post("/execute", json=classification_body())

    assert switch.status_code == 200
    assert response.json()["decision"]["mode"] == "fixed"
    assert response.json()["decision"]["reason"] == "autopilot_disabled"
    assert response.json()["model"] == "mock-strong"
    assert response.json()["attempts"][0]["reason"] == "autopilot_disabled"


def test_policy_override_is_refused_by_default(tmp_path):
    models, prices = standard_setup()
    client, _, _ = build_test_app(
        tmp_path,
        models=models,
        prices=prices,
        teams={"suporte": team("5")},
        adapters={"mock": mock_adapter(models)},
    )

    response = client.post(
        "/execute", json=classification_body(policy_override={"model": "mock-strong"})
    )

    assert response.status_code == 403
    assert response.json()["code"] == "policy_override_disabled"


def test_policy_override_forces_a_baseline_when_enabled(tmp_path):
    models, prices = standard_setup()
    client, _, _ = build_test_app(
        tmp_path,
        models=models,
        prices=prices,
        teams={"bench": team("5")},
        adapters={"mock": mock_adapter(models)},
        allow_override=True,
    )

    response = client.post(
        "/execute", json=classification_body("bench", policy_override={"model": "mock-strong"})
    )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["mode"] == "policy_override"
    assert body["model"] == "mock-strong"
    assert [a["reason"] for a in body["attempts"]] == ["policy_override"]


def test_concurrent_requests_never_overspend_the_team_budget(tmp_path):
    models, prices = standard_setup()
    client, container, app = build_test_app(
        tmp_path,
        models=models,
        prices=prices,
        teams={"suporte": team("0.0005")},  # 500 micro-USD
        adapters={"mock": mock_adapter(models)},
    )

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            return await asyncio.gather(
                *[
                    http.post("/execute", json=classification_body(max_output_tokens=16))
                    for _ in range(100)
                ]
            )

    responses = asyncio.run(run())

    statuses = [r.status_code for r in responses]
    assert set(statuses) <= {200, 402}
    assert 200 in statuses and 402 in statuses
    snapshot = container.budget.snapshot("suporte")
    assert snapshot.spent_micro <= 500
    assert snapshot.reserved_micro == 0

    # Custo contabilizado = respostas 200 + tentativas já gastas dentro de respostas 402
    # (um pedido pode escalar, ser recusado no orçamento e ainda assim ter gasto a 1.ª tentativa).
    def micro(value: str) -> int:
        return int(round(Decimal(value) * 1_000_000))

    accounted = 0
    for r in responses:
        if r.status_code == 200:
            accounted += micro(r.json()["total_cost_usd"])
        else:
            accounted += sum(micro(a["cost_usd"]) for a in r.json().get("attempts", []))
    assert accounted == snapshot.spent_micro


def test_unknown_team_is_forbidden(tmp_path):
    models, prices = standard_setup()
    client, _, _ = build_test_app(
        tmp_path,
        models=models,
        prices=prices,
        teams={"suporte": team("5")},
        adapters={"mock": mock_adapter(models)},
    )
    response = client.post("/execute", json=classification_body("marketing"))
    assert response.status_code == 403
    assert response.json()["code"] == "team_not_configured"


def test_unreported_usage_is_estimated_and_flagged(tmp_path):
    models, prices = standard_setup()
    models[0]["mock"]["reports_usage"] = False
    client, _, _ = build_test_app(
        tmp_path,
        models=models,
        prices=prices,
        teams={"suporte": team("5")},
        adapters={"mock": mock_adapter(models)},
    )
    response = client.post("/execute", json=classification_body())
    attempt = response.json()["attempts"][0]
    assert attempt["cost_estimated"] is True
    assert attempt["tokens_estimated"] is True
    assert response.json()["cost_estimated"] is True


def test_health_reports_backend_and_dialect(tmp_path):
    models, prices = standard_setup()
    client, _, _ = build_test_app(
        tmp_path,
        models=models,
        prices=prices,
        teams={"suporte": team("5")},
        adapters={"mock": mock_adapter(models)},
    )
    body = client.get("/health").json()
    assert body == {"status": "ok", "budget_backend": "memory", "database": "sqlite"}

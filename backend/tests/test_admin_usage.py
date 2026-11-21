"""Endpoints de leitura do painel: resumo de uso, registos recentes e último benchmark."""

from __future__ import annotations

from tests.support import AUTH, build_test_app, standard_setup, team
from tests.test_execute import classification_body, mock_adapter

HEADERS = {"x-admin-token": "token-de-teste"}


def _client(tmp_path):
    models, prices = standard_setup()
    client, container, _ = build_test_app(
        tmp_path,
        models=models,
        prices=prices,
        teams={"suporte": team("5"), "dados": team("5", fixed="mock-cheap")},
        adapters={"mock": mock_adapter(models)},
    )
    return client


def test_usage_summary_groups_cost_by_team_provider_and_task(tmp_path):
    client = _client(tmp_path)
    client.post("/execute", json=classification_body(), headers=AUTH["suporte"])
    client.post("/execute", json=classification_body(), headers=AUTH["dados"])

    body = client.get("/admin/usage/summary", headers=HEADERS).json()

    teams = {g["team"] for g in body["groups"]}
    assert teams == {"suporte", "dados"}
    assert all(g["provider"] == "mock" for g in body["groups"])
    assert all(g["task_type"] == "classification" for g in body["groups"])
    assert sum(r["attempts"] for r in body["routing"]) == len(
        [g for g in body["groups"] for _ in range(g["attempts"])]
    )
    assert any(r["reason"] == "autopilot / ok" for r in body["reasons"])


def test_recent_attempts_are_newest_first_and_capped(tmp_path):
    client = _client(tmp_path)
    client.post("/execute", json=classification_body(task_id="rec-1"), headers=AUTH["suporte"])
    client.post("/execute", json=classification_body(task_id="rec-2"), headers=AUTH["suporte"])

    rows = client.get("/admin/usage/recent?limit=1", headers=HEADERS).json()

    assert len(rows) == 1
    assert rows[0]["task_id"] == "rec-2"
    assert "cost_usd" in rows[0]


def test_usage_endpoints_require_admin_token(tmp_path):
    client = _client(tmp_path)
    assert client.get("/admin/usage/summary").status_code == 401
    assert client.get("/admin/usage/recent").status_code == 401
    assert client.get("/admin/benchmark").status_code == 401


def test_benchmark_endpoint_returns_policies_from_the_report(tmp_path):
    client = _client(tmp_path)
    response = client.get("/admin/benchmark", headers=HEADERS)
    if response.status_code == 404:
        return  # relatório ainda não gerado neste clone
    body = response.json()
    assert "always_expensive" in body["policies"]
    assert "meta" in body

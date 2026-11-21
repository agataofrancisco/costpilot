"""/route sem execução e endpoints /admin (autenticação e interruptor do autopilot)."""

from __future__ import annotations

from tests.support import build_test_app, standard_setup, team
from tests.test_execute import SpyAdapter, mock_adapter

ROUTE_BODY = {
    "task_type": "json_extraction",
    "input_tokens": 500,
    "requires_json": True,
    "team": "suporte",
    "cost_ceiling_usd": "0.002",
}


def _app(tmp_path, *, admin_token="token-de-teste"):
    models, prices = standard_setup()
    spy = SpyAdapter(mock_adapter(models))
    client, container, _ = build_test_app(
        tmp_path,
        models=models,
        prices=prices,
        teams={"suporte": team("5", fixed="mock-mid")},
        adapters={"mock": spy},
        admin_token=admin_token,
    )
    return client, container, spy


def test_route_explains_choice_and_exclusions_without_calling_any_provider(tmp_path):
    client, _, spy = _app(tmp_path)

    response = client.post("/route", json=ROUTE_BODY)

    assert response.status_code == 200
    body = response.json()
    assert body["chosen"] == "mock-cheap"
    assert body["mode"] == "autopilot"
    by_model = {c["model"]: c for c in body["candidates"]}
    assert by_model["mock-strong"]["reasons"] == ["over_cost_ceiling"]
    assert by_model["mock-cheap"]["eligible"] is True
    assert body["escalation_chain"][0] == "mock-cheap"
    assert spy.calls == 0


def test_route_returns_422_with_conflicts_when_nothing_fits(tmp_path):
    client, _, spy = _app(tmp_path)

    response = client.post("/route", json={**ROUTE_BODY, "cost_ceiling_usd": "0.0000001"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "no_eligible_model"
    assert len(body["conflicts"]) == 3
    assert all("over_cost_ceiling" in c for c in body["conflicts"])
    assert spy.calls == 0


def test_route_rejects_invalid_team_name_at_the_boundary(tmp_path):
    client, _, _ = _app(tmp_path)

    response = client.post("/route", json={**ROUTE_BODY, "team": "Suporte Ã"})

    assert response.status_code == 422


def test_route_rejects_unknown_fields(tmp_path):
    client, _, _ = _app(tmp_path)

    response = client.post("/route", json={**ROUTE_BODY, "campo_inventado": 1})

    assert response.status_code == 422


def test_admin_endpoints_require_the_token(tmp_path):
    client, _, _ = _app(tmp_path)

    missing = client.get("/admin/teams")
    wrong = client.get("/admin/teams", headers={"x-admin-token": "errado"})
    ok = client.get("/admin/teams", headers={"x-admin-token": "token-de-teste"})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert ok.status_code == 200
    row = ok.json()[0]
    assert row["team"] == "suporte"
    assert row["autopilot_source"] == "config"


def test_admin_is_disabled_without_a_configured_token(tmp_path):
    client, _, _ = _app(tmp_path, admin_token=None)

    response = client.get("/admin/teams", headers={"x-admin-token": "qualquer"})

    assert response.status_code == 503
    assert response.json()["code"] == "admin_disabled"


def test_autopilot_toggle_is_persisted_and_reported(tmp_path):
    client, _, _ = _app(tmp_path)
    headers = {"x-admin-token": "token-de-teste"}

    client.put("/admin/teams/suporte/autopilot", json={"enabled": False}, headers=headers)
    row = client.get("/admin/teams", headers=headers).json()[0]

    assert row["autopilot_enabled"] is False
    assert row["autopilot_source"] == "override"


def test_autopilot_toggle_for_unknown_team_is_forbidden(tmp_path):
    client, _, _ = _app(tmp_path)
    response = client.put(
        "/admin/teams/marketing/autopilot",
        json={"enabled": False},
        headers={"x-admin-token": "token-de-teste"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "team_not_configured"


def test_autopilot_toggle_rejects_non_boolean(tmp_path):
    client, _, _ = _app(tmp_path)
    response = client.put(
        "/admin/teams/suporte/autopilot",
        json={"enabled": "talvez"},
        headers={"x-admin-token": "token-de-teste"},
    )
    assert response.status_code == 422


def test_catalog_admin_view_shows_price_source_and_pricing_gap(tmp_path):
    client, _, _ = _app(tmp_path)
    rows = client.get("/admin/catalog", headers={"x-admin-token": "token-de-teste"}).json()
    by_id = {r["id"]: r for r in rows}
    assert by_id["mock-cheap"]["price_source"] == "teste"
    assert by_id["mock-cheap"]["capability_mismatches"] == []

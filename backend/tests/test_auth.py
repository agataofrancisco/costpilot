"""Autenticação por chave: 401, team/tenant fora do corpo, isolamento de orçamento e cache."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.auth.clients import ClientRegistry, hash_key
from app.catalog.pricing import ConfigError

from tests.support import AUTH, TEST_CLIENTS, build_test_app, standard_setup, team
from tests.test_execute import classification_body, mock_adapter

REPO_CLIENTS = Path(__file__).resolve().parents[2] / "config" / "clients.yaml"


def _app(tmp_path: Path, **kwargs):
    models, prices = standard_setup()
    return build_test_app(
        tmp_path,
        models=models,
        prices=prices,
        teams={"suporte": team("5"), "dados": team("5", fixed="mock-cheap")},
        adapters={"mock": mock_adapter(models)},
        **kwargs,
    )


# --- 401 -----------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/route", "/execute"])
def test_request_without_key_is_401(tmp_path, path):
    client, _, _ = _app(tmp_path)
    body = (
        {"task_type": "classification", "input_tokens": 10}
        if path == "/route"
        else classification_body()
    )
    response = client.post(path, json=body, headers={"Authorization": ""})

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


def test_unknown_key_is_401(tmp_path):
    client, _, _ = _app(tmp_path)
    response = client.post(
        "/execute", json=classification_body(), headers={"Authorization": "Bearer nao-existe"}
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    "header", ["Basic dXNlcjpwYXNz", "Bearer", "Bearer   ", "Token chave-teste-suporte"]
)
def test_malformed_authorization_header_is_401(tmp_path, header):
    client, _, _ = _app(tmp_path)
    response = client.post(
        "/execute", json=classification_body(), headers={"Authorization": header}
    )
    assert response.status_code == 401


def test_401_is_returned_before_any_budget_is_touched(tmp_path):
    client, container, _ = _app(tmp_path)
    client.post("/execute", json=classification_body(), headers={"Authorization": "Bearer x"})
    assert container.budget.snapshot("suporte").spent_micro == 0


# --- team/tenant nunca vêm do corpo ---------------------------------------------------


def test_team_in_body_is_rejected_with_422(tmp_path):
    client, container, _ = _app(tmp_path)
    body = classification_body()
    body["task"]["team"] = "dados"

    response = client.post("/execute", json=body, headers=AUTH["suporte"])

    assert response.status_code == 422
    assert container.budget.snapshot("dados").spent_micro == 0
    assert container.budget.snapshot("suporte").spent_micro == 0


def test_tenant_in_body_is_rejected_on_route_too(tmp_path):
    client, _, _ = _app(tmp_path)
    response = client.post(
        "/route",
        json={"task_type": "classification", "input_tokens": 10, "tenant_id": "cliente-a"},
        headers=AUTH["suporte"],
    )
    assert response.status_code == 422


# --- orçamento: a chave da equipa A não gasta o orçamento da equipa B -----------------


def test_team_a_key_cannot_spend_team_b_budget(tmp_path):
    client, container, _ = _app(tmp_path)

    # Equipa suporte gasta; a equipa dados continua intacta.
    spent_by_suporte = client.post("/execute", json=classification_body(), headers=AUTH["suporte"])
    assert spent_by_suporte.status_code == 200
    assert container.budget.snapshot("suporte").spent_micro > 0
    assert container.budget.snapshot("dados").spent_micro == 0

    # Tentar afirmar a equipa dados no corpo, com a chave de suporte, não gasta nada de dados.
    claim = classification_body()
    claim["task"]["team"] = "dados"
    assert client.post("/execute", json=claim, headers=AUTH["suporte"]).status_code == 422
    assert container.budget.snapshot("dados").spent_micro == 0


def test_each_key_only_spends_its_own_team(tmp_path):
    client, container, _ = _app(tmp_path)
    client.post("/execute", json=classification_body(), headers=AUTH["dados"])

    assert container.budget.snapshot("dados").spent_micro > 0
    assert container.budget.snapshot("suporte").spent_micro == 0


# --- cache: nunca partilhada entre equipas ou tenants, mesmo que o corpo minta -------


def test_cache_is_not_shared_between_teams(tmp_path):
    client, _, _ = _app(tmp_path)
    body = classification_body(cache=True, temperature=0)

    first = client.post("/execute", json=body, headers=AUTH["suporte"])
    second = client.post("/execute", json=body, headers=AUTH["dados"])

    assert first.json()["cache"] == "miss"
    assert second.json()["cache"] == "miss"
    assert "x-modelmesh-cache" not in second.headers


def test_cache_is_not_shared_between_tenants_of_the_same_team(tmp_path):
    client, _, _ = _app(tmp_path)
    body = classification_body(cache=True, temperature=0)

    # cliente-a e suporte (orbita-tech) têm a mesma equipa "suporte" mas tenants diferentes.
    first = client.post("/execute", json=body, headers=AUTH["cliente-a"])
    second = client.post("/execute", json=body, headers=AUTH["cliente-b"])
    third = client.post("/execute", json=body, headers=AUTH["suporte"])

    assert [r.json()["cache"] for r in (first, second, third)] == ["miss", "miss", "miss"]


def test_same_key_does_hit_its_own_cache(tmp_path):
    client, _, _ = _app(tmp_path)
    body = classification_body(cache=True, temperature=0)

    client.post("/execute", json=body, headers=AUTH["cliente-a"])
    again = client.post("/execute", json=body, headers=AUTH["cliente-a"])

    assert again.json()["cache"] == "hit"


# --- armazenamento: só digests ---------------------------------------------------------


def test_registry_never_holds_plaintext_keys(tmp_path):
    client, container, _ = _app(tmp_path)
    dump = repr(vars(container.clients))
    for entry in TEST_CLIENTS:
        assert entry["key"] not in dump
        assert hash_key(entry["key"]) in dump


def test_repository_clients_file_contains_no_plaintext_demo_key():
    # Os comentários documentam o formato da chave de demo; as linhas de dados só têm digests.
    data_lines = [
        line
        for line in REPO_CLIENTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    for team_name in ("suporte", "marketing", "dados", "bench"):
        assert not any(f"cp-demo-{team_name}-2026" in line for line in data_lines)


def test_demo_keys_in_repository_config_authenticate_to_fixed_principals():
    registry = ClientRegistry.load(REPO_CLIENTS)

    suporte = registry.authenticate("Bearer cp-demo-suporte-2026")
    dados = registry.authenticate("Bearer cp-demo-dados-2026")

    assert (suporte.tenant_id, suporte.team) == ("orbita-tech", "suporte")
    assert (dados.tenant_id, dados.team) == ("orbita-tech", "dados")


def test_bearer_scheme_is_case_insensitive(tmp_path):
    registry = ClientRegistry.load(REPO_CLIENTS)
    assert registry.authenticate("bearer cp-demo-suporte-2026").team == "suporte"


@pytest.mark.parametrize(
    "content",
    [
        "clients:\n  - name: x\n    tenant_id: t\n    team: suporte\n    key_sha256: ABC\n",
        "clients:\n  - name: x\n    tenant_id: t\n    team: 'Suporte X'\n"
        "    key_sha256: " + "a" * 64 + "\n",
    ],
)
def test_invalid_clients_file_fails_at_load_time(tmp_path, content):
    path = tmp_path / "clients.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigError):
        ClientRegistry.load(path)


def test_duplicate_key_digest_is_rejected(tmp_path):
    digest = hash_key("mesma-chave")
    entry = f"  - name: a\n    tenant_id: t\n    team: suporte\n    key_sha256: {digest}\n"
    path = tmp_path / "clients.yaml"
    path.write_text("clients:\n" + entry + entry.replace("name: a", "name: b"), encoding="utf-8")
    with pytest.raises(ConfigError, match="duplicada"):
        ClientRegistry.load(path)


def test_empty_registry_rejects_every_key(tmp_path):
    from app.routing.errors import Unauthorized

    path = tmp_path / "clients.yaml"
    path.write_text("clients: []\n", encoding="utf-8")
    with pytest.raises(Unauthorized):
        ClientRegistry.load(path).authenticate("Bearer qualquer")

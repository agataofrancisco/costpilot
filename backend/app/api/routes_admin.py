"""Endpoints de administração. Exigem `x-admin-token` igual a `COSTPILOT_ADMIN_TOKEN`.

Sem token configurado, os endpoints ficam desactivados (503), nunca abertos por omissão.
"""

from __future__ import annotations

import hmac
import json

from fastapi import APIRouter, Depends, Header, Request

from app.api.errors import AdminDisabled, NotFound, Unauthorized
from app.api.schemas import AutopilotUpdate
from app.api.serializers import usd
from app.catalog.probes import run_capability_probes
from app.config import REPO_ROOT

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(request: Request, x_admin_token: str | None = Header(default=None)) -> None:
    secret = request.app.state.container.settings.admin_token
    if secret is None:
        raise AdminDisabled("endpoints de administração desactivados (sem COSTPILOT_ADMIN_TOKEN)")
    if x_admin_token is None or not hmac.compare_digest(x_admin_token, secret.get_secret_value()):
        raise Unauthorized("token de administração inválido")


@router.get("/teams", dependencies=[Depends(require_admin)])
def list_teams(request: Request) -> list[dict]:
    container = request.app.state.container
    overrides = container.settings_repo.overrides()
    rows = []
    for name, config in container.router.teams.items():
        snapshot = container.budget.snapshot(name)
        rows.append(
            {
                "team": name,
                "budget_usd": usd(config.budget_micro),
                "spent_usd": usd(snapshot.spent_micro),
                "reserved_usd": usd(snapshot.reserved_micro),
                "fixed_model": config.fixed_model,
                "autopilot_enabled": overrides.get(name, config.autopilot_default),
                "autopilot_source": "override" if name in overrides else "config",
            }
        )
    return rows


@router.put("/teams/{team}/autopilot", dependencies=[Depends(require_admin)])
def set_autopilot(team: str, body: AutopilotUpdate, request: Request) -> dict:
    container = request.app.state.container
    config = container.router.team(team)  # levanta TeamNotConfigured se não existir
    container.settings_repo.set_autopilot(team, body.enabled)
    return {"team": team, "autopilot_enabled": body.enabled, "fixed_model": config.fixed_model}


@router.get("/catalog", dependencies=[Depends(require_admin)])
def catalog_view(request: Request) -> list[dict]:
    container = request.app.state.container
    now = container.clock()
    rows = []
    for spec in container.catalog.models():
        price = container.catalog.price(spec.id, now.date())
        rows.append(
            {
                "id": spec.id,
                "provider": spec.provider,
                "enabled": spec.enabled,
                "supports_json_mode": spec.supports_json_mode,
                "supports_tools": spec.supports_tools,
                "allow_sensitive": spec.allow_sensitive,
                "context_window": spec.context_window,
                "price_input_per_mtok": None if price is None else str(price.input_per_mtok),
                "price_output_per_mtok": None if price is None else str(price.output_per_mtok),
                "price_source": None if price is None else price.source,
                "capability_mismatches": sorted(container.registry.mismatches(spec.id)),
            }
        )
    return rows


@router.get("/usage/summary", dependencies=[Depends(require_admin)])
def usage_summary(request: Request) -> dict:
    """Custos por equipa/provider/tarefa, distribuição de routing e motivos das decisões."""
    container = request.app.state.container
    rows = container.usage.aggregate()
    routing: dict[str, int] = {}
    reasons: dict[str, int] = {}
    for row in rows:
        routing[row["model"]] = routing.get(row["model"], 0) + row["attempts"]
        key = f"{row['reason']} / {row['status']}"
        reasons[key] = reasons.get(key, 0) + row["attempts"]
    return {
        "groups": [{**row, "cost_usd": usd(row["cost_micro"])} for row in rows],
        "routing": [{"model": m, "attempts": n} for m, n in sorted(routing.items())],
        "reasons": [{"reason": r, "attempts": n} for r, n in sorted(reasons.items())],
    }


@router.get("/usage/recent", dependencies=[Depends(require_admin)])
def usage_recent(request: Request, limit: int = 50) -> list[dict]:
    limit = max(1, min(limit, 200))
    rows = request.app.state.container.usage.recent(limit)
    return [{**row, "cost_usd": usd(int(row["cost_micro"]))} for row in rows]


@router.get("/benchmark", dependencies=[Depends(require_admin)])
def benchmark() -> dict:
    """Resumo do último benchmark (simulado). Devolve 404 se ainda não existir."""
    path = REPO_ROOT / "reports" / "ablation.json"
    if not path.exists():
        raise NotFound("ainda não há relatório de benchmark (correr bench/costpilot/runner.py)")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {"meta": payload.get("meta", {}), "policies": payload.get("policies", {})}


@router.post("/probes", dependencies=[Depends(require_admin)])
async def run_probes(request: Request) -> list[dict]:
    """Repete as sondas de JSON mode em todos os providers configurados.

    Com providers reais esta chamada gasta tokens: é a única forma de os sondar.
    """
    container = request.app.state.container
    outcomes = await run_capability_probes(
        container.catalog, container.adapters, container.registry
    )
    return [
        {"model": o.model, "capability": o.capability, "ok": o.ok, "detail": o.detail}
        for o in outcomes
    ]

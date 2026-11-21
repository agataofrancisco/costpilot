"""Endpoints de administração. Exigem `x-admin-token` igual a `COSTPILOT_ADMIN_TOKEN`.

Sem token configurado, os endpoints ficam desactivados (503), nunca abertos por omissão.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, Request

from app.api.errors import AdminDisabled, Unauthorized
from app.api.schemas import AutopilotUpdate
from app.api.serializers import usd
from app.catalog.probes import run_capability_probes
from app.routing.errors import TeamNotConfigured

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(request: Request, x_admin_token: str | None = Header(default=None)) -> None:
    expected = request.app.state.container.settings.admin_token
    if not expected:
        raise AdminDisabled("endpoints de administração desactivados (sem COSTPILOT_ADMIN_TOKEN)")
    if x_admin_token is None or not hmac.compare_digest(x_admin_token, expected):
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
    return {
        "team": team,
        "autopilot_enabled": body.enabled,
        "fixed_model": config.fixed_model,
    }


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


__all__ = ["TeamNotConfigured", "router"]

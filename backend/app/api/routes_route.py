from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.auth import AuthenticatedPrincipal
from app.api.schemas import TaskRequest
from app.api.serializers import decision_json
from app.routing.errors import NoEligibleModel

router = APIRouter()


@router.post("/route")
def route(body: TaskRequest, request: Request, principal: AuthenticatedPrincipal) -> dict:
    """Decisão explicável sem chamar nenhum provider. Equipa e tenant vêm da chave."""
    container = request.app.state.container
    task = body.to_task(principal)
    decision = container.router.route(task, container.clock())
    if decision.chosen is None:
        raise NoEligibleModel(
            "nenhum modelo cumpre as restrições em simultâneo",
            conflicts=list(decision.conflicts),
            mode=decision.mode,
        )
    return decision_json(decision)

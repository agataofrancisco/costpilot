from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.serializers import decision_json
from app.routing.errors import NoEligibleModel
from app.routing.task import TaskSpec

router = APIRouter()


@router.post("/route")
def route(task: TaskSpec, request: Request) -> dict:
    """Decisão explicável sem chamar nenhum provider."""
    container = request.app.state.container
    decision = container.router.route(task, container.clock())
    if decision.chosen is None:
        raise NoEligibleModel(
            "nenhum modelo cumpre as restrições em simultâneo",
            conflicts=list(decision.conflicts),
            mode=decision.mode,
        )
    return decision_json(decision)

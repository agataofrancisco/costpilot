from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
def health(request: Request) -> dict[str, object]:
    container = request.app.state.container
    return {
        "status": "ok",
        "budget_backend": container.budget_backend_name,
        "database": container.database_dialect,
    }

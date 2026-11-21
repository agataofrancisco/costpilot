"""Tradução dos erros de domínio para respostas HTTP com um `code` estável."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.serializers import attempt_json, to_jsonable, usd
from app.routing.errors import RoutingError


class Unauthorized(RoutingError):
    status_code = 401
    code = "unauthorized"


class NotFound(RoutingError):
    status_code = 404
    code = "not_found"


class AdminDisabled(RoutingError):
    status_code = 503
    code = "admin_disabled"


def _details(details: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {}
    for key, value in details.items():
        if key == "attempts":
            body["attempts"] = [attempt_json(a) for a in value]
        elif key in ("spent_micro", "reserved_micro", "budget_micro", "attempt_reserved_micro"):
            body[key.replace("_micro", "_usd")] = usd(int(value))
        else:
            body[key] = to_jsonable(value)
    return body


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RoutingError)
    async def _routing_error(request: Request, exc: RoutingError) -> JSONResponse:
        content = {"code": exc.code, "message": exc.message, **_details(exc.details)}
        return JSONResponse(status_code=exc.status_code, content=content)

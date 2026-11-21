"""Dependência FastAPI que identifica o cliente pela chave `Authorization: Bearer <chave>`."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request

from app.auth.clients import Principal


def get_principal(request: Request, authorization: str | None = Header(default=None)) -> Principal:
    return request.app.state.container.clients.authenticate(authorization)


# Alias de tipo: evita `Depends(...)` nos valores por omissão (regra B008).
AuthenticatedPrincipal = Annotated[Principal, Depends(get_principal)]

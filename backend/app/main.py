"""Ponto de entrada da API FastAPI.

Execução local (demo):
    uvicorn app.main:create_app --factory --app-dir backend --port 8000
A factory evita construir a base de dados e os providers ao importar o módulo.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_error_handlers
from app.api.health import router as health_router
from app.api.routes_admin import router as admin_router
from app.api.routes_execute import router as execute_router
from app.api.routes_route import router as route_router
from app.catalog.probes import run_capability_probes
from app.config import Settings, get_settings
from app.container import Container, build_container


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    app_container = container or build_container(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Ao arranque só se sondam providers locais (mock). Providers reais gastam tokens:
        # ficam para `POST /admin/probes`.
        if app.state.container.settings.probe_on_startup:
            current = app.state.container
            await run_capability_probes(
                current.catalog,
                current.adapters,
                current.registry,
                only_providers=frozenset({"mock"}),
            )
        yield

    app = FastAPI(title="CostPilot", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.container = app_container
    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(route_router)
    app.include_router(execute_router)
    app.include_router(admin_router)
    return app

"""Ponto de entrada da API FastAPI.

Execução local (demo):  uvicorn app.main:app --app-dir backend --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.health import router as health_router
from app.config import Settings, get_settings
from app.container import Container, build_container


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="CostPilot", version="0.1.0")
    app.state.settings = settings
    app.state.container = container or build_container(settings)
    app.include_router(health_router)
    return app


app = create_app()

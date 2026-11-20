"""Composição das dependências (sem globais mutáveis; cada app tem o seu container)."""

from __future__ import annotations

from dataclasses import dataclass

import redis

from app.accounting.db import init_schema, make_engine, make_session_factory
from app.accounting.repository import UsageRepository
from app.budget.redis_store import RedisBudgetStore
from app.budget.store import BudgetStore, InMemoryBudgetStore
from app.config import Settings


@dataclass
class Container:
    settings: Settings
    budget: BudgetStore
    budget_backend_name: str
    usage: UsageRepository
    database_dialect: str


def build_container(settings: Settings) -> Container:
    engine = make_engine(settings.database_url)
    init_schema(engine)
    if settings.redis_url:
        budget: BudgetStore = RedisBudgetStore(redis.Redis.from_url(settings.redis_url))
        backend_name = "redis"
    else:
        budget = InMemoryBudgetStore()
        backend_name = "memory"
    return Container(
        settings=settings,
        budget=budget,
        budget_backend_name=backend_name,
        usage=UsageRepository(make_session_factory(engine)),
        database_dialect=engine.dialect.name,
    )

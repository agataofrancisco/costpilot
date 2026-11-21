"""Composição das dependências. Cada aplicação tem o seu container (sem globais mutáveis)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import redis

from app.accounting.db import init_schema, make_engine, make_session_factory
from app.accounting.repository import UsageRepository
from app.accounting.settings_repo import TeamSettingsRepository
from app.budget.redis_store import RedisBudgetStore
from app.budget.store import BudgetStore, InMemoryBudgetStore
from app.cache.store import MemoryResponseCache, RedisResponseCache, ResponseCache
from app.catalog.catalog import Catalog
from app.catalog.probes import ProbeRegistry
from app.config import Settings
from app.providers.base import ProviderAdapter
from app.providers.mock import MockAdapter
from app.providers.modelmesh import build_modelmesh_adapter
from app.providers.openai_compatible import OpenAICompatibleAdapter
from app.routing.config_loader import load_policy, load_teams
from app.routing.executor import Executor
from app.routing.router import Router

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Container:
    settings: Settings
    catalog: Catalog
    registry: ProbeRegistry
    adapters: dict[str, ProviderAdapter]
    budget: BudgetStore
    budget_backend_name: str
    cache: ResponseCache
    usage: UsageRepository
    settings_repo: TeamSettingsRepository
    router: Router
    executor: Executor
    clock: Clock
    database_dialect: str


def build_adapters(
    settings: Settings, catalog: Catalog, overrides: Mapping[str, ProviderAdapter] | None = None
) -> dict[str, ProviderAdapter]:
    adapters: dict[str, ProviderAdapter] = {}
    if settings.mock_enabled and catalog.mock_profiles():
        adapters["mock"] = MockAdapter(catalog.mock_profiles(), seed=settings.mock_seed)
    if settings.openai_base_url:
        adapters["openai_compatible"] = OpenAICompatibleAdapter(
            name="openai_compatible",
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            timeout_seconds=settings.provider_timeout_seconds,
        )
    if settings.modelmesh_base_url:
        adapters["modelmesh"] = build_modelmesh_adapter(
            settings.modelmesh_base_url,
            settings.modelmesh_virtual_key,
            settings.provider_timeout_seconds,
        )
    adapters.update(overrides or {})
    return adapters


def build_container(
    settings: Settings,
    *,
    adapters: Mapping[str, ProviderAdapter] | None = None,
    clock: Clock | None = None,
) -> Container:
    engine = make_engine(settings.database_url)
    init_schema(engine)
    sessions = make_session_factory(engine)
    now = clock or utc_now

    catalog = Catalog.load(settings.config_dir)
    policy = load_policy(settings.config_dir / "policy.yaml")
    teams = load_teams(settings.config_dir / "teams.yaml")
    catalog.ensure_known(team.fixed_model for team in teams.values())
    wired_adapters = build_adapters(settings, catalog, adapters)

    if settings.redis_url:
        client = redis.Redis.from_url(settings.redis_url)
        budget: BudgetStore = RedisBudgetStore(client)
        cache: ResponseCache = RedisResponseCache(client)
        backend_name = "redis"
    else:
        budget = InMemoryBudgetStore()
        cache = MemoryResponseCache()
        backend_name = "memory"

    usage = UsageRepository(sessions)
    settings_repo = TeamSettingsRepository(sessions)
    registry = ProbeRegistry()
    router = Router(
        catalog=catalog,
        registry=registry,
        usage=usage,
        policy=policy,
        teams=teams,
        settings=settings_repo,
        available_providers=frozenset(wired_adapters),
    )
    executor = Executor(
        router=router,
        adapters=wired_adapters,
        budget=budget,
        usage=usage,
        cache=cache,
        settings=settings,
        clock=now,
    )
    return Container(
        settings=settings,
        catalog=catalog,
        registry=registry,
        adapters=wired_adapters,
        budget=budget,
        budget_backend_name=backend_name,
        cache=cache,
        usage=usage,
        settings_repo=settings_repo,
        router=router,
        executor=executor,
        clock=now,
        database_dialect=engine.dialect.name,
    )

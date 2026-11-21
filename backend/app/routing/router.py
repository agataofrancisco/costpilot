"""Router: junta factos do catálogo e histórico à política pura. Não executa nada."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from app.accounting.repository import UsageRepository
from app.accounting.settings_repo import TeamSettingsRepository
from app.catalog.catalog import Catalog
from app.catalog.facts import CandidateFacts, build_candidates
from app.catalog.probes import ProbeRegistry
from app.routing.config_loader import RoutingPolicy, TeamConfig
from app.routing.decision import Decision
from app.routing.errors import TeamNotConfigured
from app.routing.policy import decide, decide_override
from app.routing.task import TaskSpec


class Router:
    def __init__(
        self,
        *,
        catalog: Catalog,
        registry: ProbeRegistry,
        usage: UsageRepository,
        policy: RoutingPolicy,
        teams: Mapping[str, TeamConfig],
        settings: TeamSettingsRepository,
        available_providers: frozenset[str],
    ) -> None:
        self._catalog = catalog
        self._registry = registry
        self._usage = usage
        self._policy = policy
        self._teams = dict(teams)
        self._settings = settings
        self._available = available_providers

    @property
    def policy(self) -> RoutingPolicy:
        return self._policy

    @property
    def catalog(self) -> Catalog:
        return self._catalog

    @property
    def teams(self) -> Mapping[str, TeamConfig]:
        return dict(self._teams)

    @property
    def available_providers(self) -> frozenset[str]:
        return self._available

    def team(self, name: str) -> TeamConfig:
        config = self._teams.get(name)
        if config is None:
            raise TeamNotConfigured(f"equipa '{name}' não configurada", team=name)
        return config

    def candidates(self, task: TaskSpec, when: datetime) -> list[CandidateFacts]:
        return build_candidates(
            self._catalog,
            registry=self._registry,
            samples_for=lambda model, task_type: self._usage.judged_samples(
                model, task_type, limit=self._policy.history_window
            ),
            task_type=task.task_type,
            when=when.date(),
            prior_strength=self._policy.prior_strength,
            min_latency_samples=self._policy.min_latency_samples,
        )

    def autopilot_enabled(self, team: TeamConfig) -> bool:
        return self._settings.autopilot_enabled(team.name, team.autopilot_default)

    def route(self, task: TaskSpec, when: datetime) -> Decision:
        team = self.team(task.team)
        return decide(
            task,
            self.candidates(task, when),
            self._policy,
            autopilot_enabled=self.autopilot_enabled(team),
            fixed_model=team.fixed_model,
            available_providers=self._available,
        )

    def override(self, task: TaskSpec, when: datetime, model: str) -> Decision:
        self.team(task.team)
        return decide_override(
            task, self.candidates(task, when), model, available_providers=self._available
        )

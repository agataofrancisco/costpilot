"""Carregamento e validação de `config/policy.yaml` e `config/teams.yaml` (falha no arranque)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.budget.money import usd_to_micro_ceil
from app.catalog.models import TASK_TYPES
from app.catalog.pricing import ConfigError, parse_decimal

TEAM_PATTERN = re.compile(r"^[a-z0-9_-]{1,40}$")


@dataclass(frozen=True, slots=True)
class RoutingPolicy:
    quality_targets: Mapping[str, float]
    prior_strength: float
    min_latency_samples: int
    history_window: int
    default_output_tokens: Mapping[str, int]
    max_attempts: int


@dataclass(frozen=True, slots=True)
class TeamConfig:
    name: str
    budget_micro: int
    fixed_model: str
    autopilot_default: bool


def _load_yaml(path: Path) -> Any:
    if not path.exists():
        raise ConfigError(f"ficheiro de configuração em falta: {path.name}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _per_task(raw: object, where: str, *, integer: bool) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{where}: tem de ser um mapa por tipo de tarefa")
    missing = TASK_TYPES - set(raw)
    if missing:
        raise ConfigError(f"{where}: faltam tipos de tarefa {sorted(missing)}")
    unknown = set(raw) - TASK_TYPES
    if unknown:
        raise ConfigError(f"{where}: tipos desconhecidos {sorted(unknown)}")
    result: dict[str, Any] = {}
    for task_type, value in raw.items():
        if integer:
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ConfigError(f"{where}.{task_type}: inteiro positivo esperado")
            result[task_type] = value
        else:
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ConfigError(f"{where}.{task_type}: número esperado")
            if not 0.0 <= float(value) <= 1.0:
                raise ConfigError(f"{where}.{task_type}: fora de [0, 1]")
            result[task_type] = float(value)
    return result


def load_policy(path: Path) -> RoutingPolicy:
    raw = _load_yaml(path)
    if not isinstance(raw, Mapping):
        raise ConfigError("policy.yaml: raiz tem de ser um mapa")
    strength = raw.get("prior_strength")
    if isinstance(strength, bool) or not isinstance(strength, int | float) or strength <= 0:
        raise ConfigError("policy.yaml: prior_strength tem de ser positivo")
    min_samples = raw.get("min_latency_samples")
    window = raw.get("history_window")
    attempts = raw.get("max_attempts")
    for name, value, low, high in (
        ("min_latency_samples", min_samples, 1, 10_000),
        ("history_window", window, 1, 100_000),
        ("max_attempts", attempts, 1, 5),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ConfigError(f"policy.yaml: {name} fora do intervalo [{low}, {high}]")
    return RoutingPolicy(
        quality_targets=_per_task(raw.get("quality_targets"), "quality_targets", integer=False),
        prior_strength=float(strength),
        min_latency_samples=min_samples,
        history_window=window,
        default_output_tokens=_per_task(
            raw.get("default_output_tokens"), "default_output_tokens", integer=True
        ),
        max_attempts=attempts,
    )


def load_teams(path: Path) -> dict[str, TeamConfig]:
    raw = _load_yaml(path)
    if not isinstance(raw, Mapping) or not isinstance(raw.get("teams"), Mapping):
        raise ConfigError("teams.yaml: raiz tem de ter o mapa 'teams'")
    teams: dict[str, TeamConfig] = {}
    for name, entry in raw["teams"].items():
        if not isinstance(name, str) or not TEAM_PATTERN.match(name):
            raise ConfigError(f"teams.yaml: nome de equipa inválido: {name!r}")
        if not isinstance(entry, Mapping):
            raise ConfigError(f"teams.yaml: {name} tem de ser um mapa")
        budget = parse_decimal(entry.get("budget_usd"), f"teams.{name}.budget_usd")
        fixed = entry.get("fixed_model")
        if not isinstance(fixed, str) or not fixed:
            raise ConfigError(f"teams.yaml: {name}.fixed_model em falta")
        autopilot = entry.get("autopilot_default")
        if not isinstance(autopilot, bool):
            raise ConfigError(f"teams.yaml: {name}.autopilot_default tem de ser true/false")
        teams[name] = TeamConfig(
            name=name,
            budget_micro=usd_to_micro_ceil(budget),
            fixed_model=fixed,
            autopilot_default=autopilot,
        )
    return teams

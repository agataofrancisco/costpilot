"""Especificação dos modelos do catálogo, carregada e validada a partir de `config/models.yaml`.

A validação é defensiva: a configuração é a fonte de verdade da política, por isso um erro
aqui falha no arranque com uma mensagem clara, e nunca chega à decisão.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.catalog.pricing import ConfigError
from app.providers.mock import MockProfile

PROVIDERS = frozenset({"mock", "openai_compatible", "modelmesh"})
TASK_TYPES = frozenset({"classification", "json_extraction", "multi_step_reasoning", "doc_qa"})
DEFAULT_PRIOR = 0.5
_MODEL_ID = re.compile(r"^[A-Za-z0-9._/:-]{1,120}$")


@dataclass(frozen=True, slots=True)
class ModelSpec:
    id: str
    provider: str
    context_window: int
    supports_json_mode: bool
    supports_tools: bool
    typical_latency_ms: float
    allow_sensitive: bool
    enabled: bool
    prior_success: Mapping[str, float] = field(default_factory=dict)
    mock: MockProfile | None = None

    def prior_for(self, task_type: str) -> float:
        return self.prior_success.get(task_type, DEFAULT_PRIOR)


def _str(raw: Mapping[str, Any], key: str, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{where}: '{key}' em falta ou inválido")
    return value


def _int(raw: Mapping[str, Any], key: str, where: str, minimum: int = 0) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigError(f"{where}: '{key}' tem de ser inteiro >= {minimum}")
    return value


def _float(raw: Mapping[str, Any], key: str, where: str, low: float, high: float) -> float:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"{where}: '{key}' tem de ser numérico")
    if not low <= float(value) <= high:
        raise ConfigError(f"{where}: '{key}' fora do intervalo [{low}, {high}]")
    return float(value)


def _bool(raw: Mapping[str, Any], key: str, where: str, default: bool | None = None) -> bool:
    if key not in raw and default is not None:
        return default
    value = raw.get(key)
    if not isinstance(value, bool):
        raise ConfigError(f"{where}: '{key}' tem de ser true/false")
    return value


def _priors(raw: Any, where: str) -> dict[str, float]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{where}: 'prior_success' tem de ser um mapa")
    priors: dict[str, float] = {}
    for task_type, value in raw.items():
        if task_type not in TASK_TYPES:
            raise ConfigError(f"{where}: tipo de tarefa desconhecido em prior_success: {task_type}")
        priors[task_type] = _float({"v": value}, "v", where, 0.0, 1.0)
    return priors


def _mock_profile(raw: Any, where: str) -> MockProfile:
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{where}: 'mock' tem de ser um mapa")
    quality_raw = raw.get("quality", {})
    if not isinstance(quality_raw, Mapping):
        raise ConfigError(f"{where}: 'mock.quality' tem de ser um mapa")
    quality: dict[str, float] = {}
    for task_type, value in quality_raw.items():
        if task_type not in TASK_TYPES:
            raise ConfigError(f"{where}: tipo de tarefa desconhecido em mock.quality: {task_type}")
        quality[task_type] = _float({"v": value}, "v", where, 0.0, 1.0)
    return MockProfile(
        quality=quality,
        failure_rate=_float(raw, "failure_rate", where, 0.0, 1.0) if "failure_rate" in raw else 0.0,
        latency_ms=_float(raw, "latency_ms", where, 0.0, 600_000.0)
        if "latency_ms" in raw
        else 50.0,
        json_mode_honest=_bool(raw, "json_mode_honest", where, default=True),
        reports_usage=_bool(raw, "reports_usage", where, default=True),
    )


def parse_model(raw: object, index: int) -> ModelSpec:
    where = f"models[{index}]"
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{where}: tem de ser um mapa")
    model_id = _str(raw, "id", where)
    if not _MODEL_ID.match(model_id):
        raise ConfigError(f"{where}: id de modelo inválido")
    where = f"models[{index}] ({model_id})"
    provider = _str(raw, "provider", where)
    if provider not in PROVIDERS:
        raise ConfigError(f"{where}: provider desconhecido '{provider}'")
    mock = None
    if provider == "mock":
        if "mock" not in raw:
            raise ConfigError(f"{where}: provider mock exige o bloco 'mock'")
        mock = _mock_profile(raw["mock"], where)
    return ModelSpec(
        id=model_id,
        provider=provider,
        context_window=_int(raw, "context_window", where, minimum=1),
        supports_json_mode=_bool(raw, "supports_json_mode", where),
        supports_tools=_bool(raw, "supports_tools", where),
        typical_latency_ms=_float(raw, "typical_latency_ms", where, 0.0, 600_000.0),
        allow_sensitive=_bool(raw, "allow_sensitive", where),
        enabled=_bool(raw, "enabled", where, default=True),
        prior_success=_priors(raw.get("prior_success"), where),
        mock=mock,
    )


def parse_models(raw: object) -> list[ModelSpec]:
    if not isinstance(raw, Mapping) or not isinstance(raw.get("models"), list):
        raise ConfigError("models.yaml: raiz tem de ter a lista 'models'")
    specs = [parse_model(item, index) for index, item in enumerate(raw["models"])]
    seen: set[str] = set()
    for spec in specs:
        if spec.id in seen:
            raise ConfigError(f"models.yaml: id duplicado '{spec.id}'")
        seen.add(spec.id)
    return specs

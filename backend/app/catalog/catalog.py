"""Catálogo em memória: modelos + preços + resultados das sondas de capacidade.

É a única fonte que a política consulta. Não faz I/O depois do arranque, excepto o admin
que volta a correr sondas (ver `api/routes_admin.py`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path

import yaml

from app.catalog.models import ModelSpec, parse_models
from app.catalog.pricing import ConfigError, PriceEntry, PriceTable
from app.providers.mock import MockProfile


class Catalog:
    def __init__(self, models: Iterable[ModelSpec], prices: PriceTable) -> None:
        self._models: dict[str, ModelSpec] = {m.id: m for m in models}
        self._prices = prices

    @classmethod
    def load(cls, config_dir: Path) -> Catalog:
        models_raw = yaml.safe_load((config_dir / "models.yaml").read_text(encoding="utf-8"))
        prices = PriceTable.from_yaml(config_dir / "prices.yaml")
        return cls(parse_models(models_raw), prices)

    def get(self, model_id: str) -> ModelSpec | None:
        return self._models.get(model_id)

    def models(self) -> list[ModelSpec]:
        return list(self._models.values())

    def price(self, model_id: str, when: date) -> PriceEntry | None:
        return self._prices.price_at(model_id, when)

    def mock_profiles(self) -> dict[str, MockProfile]:
        return {m.id: m.mock for m in self._models.values() if m.mock is not None}

    def ensure_known(self, model_ids: Iterable[str]) -> None:
        unknown = sorted(set(model_ids) - set(self._models))
        if unknown:
            raise ConfigError(f"modelos desconhecidos na configuração: {', '.join(unknown)}")


def priors_by_model(catalog: Catalog) -> Mapping[str, Mapping[str, float]]:
    return {m.id: m.prior_success for m in catalog.models()}

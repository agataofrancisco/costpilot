"""Tabela de preços versionada (YAML) e cálculo do custo de uma tentativa.

Um modelo só tem preço em vigor se existir uma linha com `effective_date <= data do pedido`.
Os valores são por milhão de tokens. Só USD é aceite: não há conversão de moeda.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from app.providers.base import Usage

MILLION = Decimal(1_000_000)


class ConfigError(ValueError):
    """Configuração inválida detectada no arranque."""


@dataclass(frozen=True, slots=True)
class PriceEntry:
    model: str
    input_per_mtok: Decimal
    output_per_mtok: Decimal
    effective_date: date
    source: str
    cached_input_per_mtok: Decimal | None = None
    currency: str = "USD"


def _decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ConfigError(f"{field_name}: valor numérico em falta")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ConfigError(f"{field_name}: valor numérico inválido") from exc
    if result < 0:
        raise ConfigError(f"{field_name}: não pode ser negativo")
    return result


def _date(value: object, field_name: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ConfigError(f"{field_name}: data inválida") from exc
    raise ConfigError(f"{field_name}: data em falta")


def parse_price_rows(raw: object) -> list[PriceEntry]:
    if not isinstance(raw, Mapping):
        raise ConfigError("prices.yaml: raiz tem de ser um mapa")
    currency = raw.get("currency", "USD")
    if currency != "USD":
        raise ConfigError("prices.yaml: só USD é suportado")
    rows = raw.get("prices")
    if not isinstance(rows, list):
        raise ConfigError("prices.yaml: 'prices' tem de ser uma lista")
    entries: list[PriceEntry] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ConfigError(f"prices[{index}]: tem de ser um mapa")
        model = row.get("model")
        if not isinstance(model, str) or not model:
            raise ConfigError(f"prices[{index}]: 'model' em falta")
        cached = row.get("cached_input_per_mtok")
        entries.append(
            PriceEntry(
                model=model,
                input_per_mtok=_decimal(row.get("input_per_mtok"), f"prices[{index}].input"),
                output_per_mtok=_decimal(row.get("output_per_mtok"), f"prices[{index}].output"),
                effective_date=_date(row.get("effective_date"), f"prices[{index}].effective_date"),
                source=str(row.get("source") or "TODO: indicar fonte"),
                cached_input_per_mtok=(
                    None if cached is None else _decimal(cached, f"prices[{index}].cached")
                ),
            )
        )
    return entries


class PriceTable:
    def __init__(self, entries: Iterable[PriceEntry]) -> None:
        self._by_model: dict[str, list[PriceEntry]] = {}
        for entry in entries:
            self._by_model.setdefault(entry.model, []).append(entry)
        for history in self._by_model.values():
            history.sort(key=lambda e: e.effective_date)

    @classmethod
    def from_yaml(cls, path: Path) -> PriceTable:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(parse_price_rows(raw))

    def models(self) -> list[str]:
        return sorted(self._by_model)

    def price_at(self, model: str, when: date) -> PriceEntry | None:
        """Preço em vigor: a linha mais recente com `effective_date <= when`."""
        candidates = [e for e in self._by_model.get(model, []) if e.effective_date <= when]
        return candidates[-1] if candidates else None


def cost_usd(entry: PriceEntry, usage: Usage) -> Decimal:
    """Custo exacto de uma tentativa.

    `output_tokens` já inclui os reasoning tokens (em APIs compatíveis com OpenAI o
    `completion_tokens` inclui-os), por isso não são somados outra vez.
    `input_tokens` inclui os tokens em cache; esses são cobrados ao preço de cache quando existe.
    """
    cached = min(usage.cached_tokens, usage.input_tokens)
    uncached = usage.input_tokens - cached
    cached_price = entry.cached_input_per_mtok
    if cached_price is None:
        cached_price = entry.input_per_mtok
    total = (
        Decimal(uncached) * entry.input_per_mtok
        + Decimal(cached) * cached_price
        + Decimal(usage.output_tokens) * entry.output_per_mtok
    )
    return total / MILLION

"""Regras de contabilidade de uma tentativa: estimativas e o que se cobra quando há falha.

Regra de falha: se o provider nunca processou o pedido (ligação recusada, rate limit, auth, modelo
inexistente, pedido inválido), não há custo. Se pode ter processado (timeout, erro 5xx, resposta
inválida), cobra-se a reserva inteira: é a estimativa conservadora e fica marcada como estimada.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from decimal import Decimal

from app.budget.money import usd_to_micro_ceil
from app.catalog.pricing import MILLION, PriceEntry
from app.providers.base import FailureKind

CHARGE_RESERVED_ON = frozenset(
    {FailureKind.TIMEOUT, FailureKind.UPSTREAM_ERROR, FailureKind.INVALID_RESPONSE}
)


def failure_charge_micro(kind: FailureKind, reserved_micro: int) -> int:
    return reserved_micro if kind in CHARGE_RESERVED_ON else 0


def estimate_tokens(chars: int) -> int:
    """Aproximação grosseira (~4 caracteres por token). Só usada quando o provider não reporta."""
    return math.ceil(max(chars, 0) / 4)


def prompt_chars(messages: Iterable[Mapping[str, str]]) -> int:
    return sum(len(str(m.get("content", ""))) for m in messages)


def worst_case_micro(price: PriceEntry, input_tokens: int, max_output_tokens: int) -> int:
    """Limite superior do custo de uma tentativa: é o que se reserva antes de chamar o provider."""
    usd = (
        Decimal(input_tokens) * price.input_per_mtok
        + Decimal(max_output_tokens) * price.output_per_mtok
    ) / MILLION
    return usd_to_micro_ceil(usd)

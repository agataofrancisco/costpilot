"""Dinheiro em micro-USD inteiros (1 micro-USD = 0,000001 USD).

Os orçamentos nunca usam floats: o Lua do Redis trabalha com inteiros e a soma de
reservas fica exacta. Arredondamentos para cima (ROUND_CEILING) são conservadores.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

MICRO_PER_USD = 1_000_000
_SIX_PLACES = Decimal("0.000001")


def usd_to_micro_ceil(amount: Decimal) -> int:
    if not isinstance(amount, Decimal):
        raise TypeError("o montante tem de ser Decimal")
    if amount < 0:
        raise ValueError("o montante não pode ser negativo")
    return int((amount * MICRO_PER_USD).to_integral_value(rounding=ROUND_CEILING))


def micro_to_usd(micro: int) -> Decimal:
    if micro < 0:
        raise ValueError("o montante não pode ser negativo")
    return (Decimal(micro) / Decimal(MICRO_PER_USD)).quantize(_SIX_PLACES)

"""Contrato do orçamento: as mesmas regras valem para o store em memória e para o Lua em Redis.

Os testes correm sempre com fakeredis (que executa o Lua via lupa). O Redis real está em
`test_budget_redis_real.py` com `-m redis`.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import fakeredis
import pytest
from app.budget.money import MICRO_PER_USD, micro_to_usd, usd_to_micro_ceil
from app.budget.redis_store import RedisBudgetStore
from app.budget.store import BudgetStore, InMemoryBudgetStore

LIMIT = 1 * MICRO_PER_USD


def make_store(kind: str) -> BudgetStore:
    if kind == "memory":
        return InMemoryBudgetStore()
    server = fakeredis.FakeServer()
    return RedisBudgetStore(fakeredis.FakeRedis(server=server))


@pytest.fixture(params=["memory", "fakeredis"])
def store(request) -> BudgetStore:
    return make_store(request.param)


def test_reserve_within_limit_is_accepted_and_reserved(store: BudgetStore):
    outcome = store.reserve("suporte", "r1", 300_000, LIMIT, now_ms=1_000, ttl_ms=60_000)

    assert outcome.accepted is True
    assert outcome.reserved_micro == 300_000
    assert store.snapshot("suporte").reserved_micro == 300_000


def test_reserve_beyond_limit_is_refused_without_side_effects(store: BudgetStore):
    store.reserve("suporte", "r1", 900_000, LIMIT, now_ms=1_000, ttl_ms=60_000)

    outcome = store.reserve("suporte", "r2", 200_000, LIMIT, now_ms=1_001, ttl_ms=60_000)

    assert outcome.accepted is False
    snapshot = store.snapshot("suporte")
    assert snapshot.reserved_micro == 900_000
    assert snapshot.spent_micro == 0


def test_reconcile_moves_reserved_amount_into_spent(store: BudgetStore):
    store.reserve("suporte", "r1", 500_000, LIMIT, now_ms=1_000, ttl_ms=60_000)

    spent = store.reconcile("suporte", "r1", 120_000)

    assert spent == 120_000
    snapshot = store.snapshot("suporte")
    assert (snapshot.spent_micro, snapshot.reserved_micro) == (120_000, 0)


def test_reconcile_frees_budget_for_the_next_attempt(store: BudgetStore):
    store.reserve("suporte", "r1", 900_000, LIMIT, now_ms=1_000, ttl_ms=60_000)
    store.reconcile("suporte", "r1", 100_000)

    outcome = store.reserve("suporte", "r2", 800_000, LIMIT, now_ms=1_100, ttl_ms=60_000)

    assert outcome.accepted is True


def test_expired_reservation_is_released_on_next_operation(store: BudgetStore):
    store.reserve("suporte", "r1", 900_000, LIMIT, now_ms=1_000, ttl_ms=5_000)

    outcome = store.reserve("suporte", "r2", 900_000, LIMIT, now_ms=7_000, ttl_ms=5_000)

    assert outcome.accepted is True
    assert store.snapshot("suporte").reserved_micro == 900_000


def test_late_reconcile_after_expiry_still_charges_the_real_cost(store: BudgetStore):
    store.reserve("suporte", "r1", 400_000, LIMIT, now_ms=1_000, ttl_ms=5_000)
    store.reserve("suporte", "r2", 1, LIMIT, now_ms=9_000, ttl_ms=5_000)  # purga r1

    spent = store.reconcile("suporte", "r1", 350_000)

    assert spent == 350_000


def test_teams_are_isolated(store: BudgetStore):
    store.reserve("suporte", "r1", LIMIT, LIMIT, now_ms=1_000, ttl_ms=60_000)

    outcome = store.reserve("dados", "r1", 500_000, LIMIT, now_ms=1_000, ttl_ms=60_000)

    assert outcome.accepted is True


def test_negative_amounts_are_rejected(store: BudgetStore):
    with pytest.raises(ValueError):
        store.reserve("suporte", "r1", -1, LIMIT, now_ms=1, ttl_ms=1)
    with pytest.raises(ValueError):
        store.reconcile("suporte", "r1", -1)


def test_money_conversion_rounds_up_and_rejects_bad_input():
    assert usd_to_micro_ceil(Decimal("0.0000001")) == 1
    assert usd_to_micro_ceil(Decimal("0.02")) == 20_000
    assert micro_to_usd(1_500_000) == Decimal("1.500000")
    with pytest.raises(TypeError):
        usd_to_micro_ceil(0.02)  # type: ignore[arg-type]


@pytest.mark.parametrize("kind", ["memory", "fakeredis"])
def test_hundred_concurrent_requests_never_exceed_one_dollar(kind: str):
    """100 pedidos simultâneos, cada um com reserva de 0,02 USD e custo real de 0,02 USD."""
    store = make_store(kind)
    amount = usd_to_micro_ceil(Decimal("0.02"))

    def attempt(index: int) -> bool:
        rid = f"req-{index}"
        outcome = store.reserve("bench", rid, amount, LIMIT, now_ms=1_000, ttl_ms=60_000)
        if not outcome.accepted:
            return False
        store.reconcile("bench", rid, amount)
        return True

    with ThreadPoolExecutor(max_workers=16) as pool:
        accepted = list(pool.map(attempt, range(100)))

    snapshot = store.snapshot("bench")
    assert snapshot.spent_micro <= LIMIT
    assert snapshot.reserved_micro == 0
    assert sum(accepted) == snapshot.spent_micro // amount
    assert 0 < sum(accepted) < 100

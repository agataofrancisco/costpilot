"""Verificação de concorrência contra um Redis REAL (marcador `redis`).

Execução: definir COSTPILOT_TEST_REDIS_URL (ex.: redis://localhost:6379/15) e correr
`pytest -m redis`. Sem essa variável, ou sem servidor acessível, os testes são ignorados.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
import redis
from app.budget.money import MICRO_PER_USD, usd_to_micro_ceil
from app.budget.redis_store import RedisBudgetStore

pytestmark = pytest.mark.redis


@pytest.fixture
def real_client(redis_url: str):
    client = redis.Redis.from_url(redis_url)
    try:
        client.ping()
    except redis.RedisError:
        pytest.skip("Redis configurado mas não acessível")
    yield client
    client.close()


def test_hundred_concurrent_requests_against_real_redis(real_client):
    store = RedisBudgetStore(real_client, prefix="costpilot-test")
    team = "concorrencia-teste"
    existing_keys = real_client.keys(f"costpilot-test:{{{team}}}:*")
    if existing_keys:
        real_client.delete(*existing_keys)
    amount = usd_to_micro_ceil(Decimal("0.02"))
    limit = 1 * MICRO_PER_USD

    def attempt(index: int) -> bool:
        rid = f"req-{index}"
        outcome = store.reserve(team, rid, amount, limit, now_ms=1_000_000, ttl_ms=60_000)
        if not outcome.accepted:
            return False
        store.reconcile(team, rid, amount)
        return True

    with ThreadPoolExecutor(max_workers=16) as pool:
        accepted = list(pool.map(attempt, range(100)))

    snapshot = store.snapshot(team)
    assert sum(accepted) == 50
    assert snapshot.spent_micro == limit
    assert snapshot.reserved_micro == 0

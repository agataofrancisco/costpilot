"""Cache: chaves, elegibilidade, isolamento por tenant/equipa e TTL."""

from __future__ import annotations

from app.cache.eligibility import cache_eligibility
from app.cache.keys import cache_key
from app.cache.store import MemoryResponseCache

MSGS = [{"role": "user", "content": "olá"}]


def _key(**overrides) -> str:
    base = dict(
        tenant_id="default",
        team="suporte",
        model="mock-cheap",
        temperature=0.0,
        max_tokens=16,
        json_mode=False,
        messages=MSGS,
    )
    base.update(overrides)
    return cache_key(**base)


def test_same_request_same_key_and_any_change_changes_the_key():
    assert _key() == _key()
    assert _key(team="dados") != _key()
    assert _key(tenant_id="outro") != _key()
    assert _key(model="mock-mid") != _key()
    assert _key(max_tokens=32) != _key()
    assert _key(messages=[{"role": "user", "content": "olá!"}]) != _key()


def test_field_boundaries_cannot_collide():
    a = _key(team="a|b", tenant_id="c")
    b = _key(team="a", tenant_id="b|c")
    assert a != b


def test_eligibility_is_strict():
    assert cache_eligibility(
        requested=True, temperature=0, requires_tools=False, sensitivity="low"
    ).eligible
    assert (
        cache_eligibility(
            requested=False, temperature=0, requires_tools=False, sensitivity="low"
        ).reason
        == "cache_not_requested"
    )
    assert (
        cache_eligibility(
            requested=True, temperature=0.7, requires_tools=False, sensitivity="low"
        ).reason
        == "temperature_not_zero"
    )
    assert (
        cache_eligibility(
            requested=True, temperature=0, requires_tools=True, sensitivity="low"
        ).reason
        == "has_tools"
    )
    assert (
        cache_eligibility(
            requested=True, temperature=0, requires_tools=False, sensitivity="high"
        ).reason
        == "sensitive"
    )


def test_entries_expire_after_ttl():
    now = [1000.0]
    cache = MemoryResponseCache(clock=lambda: now[0])
    cache.set("k", "v", ttl_seconds=60)

    now[0] = 1059.0
    assert cache.get("k") == "v"
    now[0] = 1060.0
    assert cache.get("k") is None


def test_missing_key_returns_none():
    assert MemoryResponseCache().get("nao-existe") is None

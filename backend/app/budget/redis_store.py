"""Orçamento atómico em Redis.

As operações de reserva e reconciliação são scripts Lua, por isso o Redis executa cada
uma sem intercalação com outros clientes. Chaves com `{equipa}` (hash tag) mantêm todas
as chaves de uma equipa no mesmo nó num cluster. O nome da equipa é validado a montante
(apenas `[a-z0-9_-]`), por isso não pode introduzir chaves inesperadas.

Reserva expirada: se o pedido não for reconciliado dentro do TTL, a reserva é libertada
na próxima operação. Por isso o TTL tem de exceder o timeout do provider (ver config).
"""

from __future__ import annotations

from typing import Any

from app.budget.store import BudgetSnapshot, ReserveOutcome

# KEYS: spent, reserved, reservas(hash rid->montante), expiracoes(zset rid->expira_em_ms)
# ARGV: limite, montante, rid, agora_ms, expira_em_ms
RESERVE_LUA = """
local spent_key, reserved_key, amounts_key, expiries_key = KEYS[1], KEYS[2], KEYS[3], KEYS[4]
local limit = tonumber(ARGV[1])
local amount = tonumber(ARGV[2])
local rid = ARGV[3]
local now_ms = ARGV[4]
local expires_at = ARGV[5]

local expired = redis.call('ZRANGEBYSCORE', expiries_key, '-inf', now_ms)
for _, id in ipairs(expired) do
  local stale = redis.call('HGET', amounts_key, id)
  if stale then
    redis.call('DECRBY', reserved_key, stale)
  end
  redis.call('HDEL', amounts_key, id)
  redis.call('ZREM', expiries_key, id)
end

local spent = tonumber(redis.call('GET', spent_key) or '0')
local reserved = tonumber(redis.call('GET', reserved_key) or '0')
-- Active reservation IDs are unique; reject duplicates without changing ledger or expiry.
if redis.call('HEXISTS', amounts_key, rid) == 1 then
  return {0, spent, reserved}
end
if spent + reserved + amount > limit then
  return {0, spent, reserved}
end
redis.call('INCRBY', reserved_key, ARGV[2])
redis.call('HSET', amounts_key, rid, ARGV[2])
redis.call('ZADD', expiries_key, expires_at, rid)
return {1, spent, reserved + amount}
"""

# KEYS: spent, reserved, reservas, expiracoes
# ARGV: rid, custo_real
RECONCILE_LUA = """
local reserved_amount = redis.call('HGET', KEYS[3], ARGV[1])
if reserved_amount then
  redis.call('DECRBY', KEYS[2], reserved_amount)
  redis.call('HDEL', KEYS[3], ARGV[1])
  redis.call('ZREM', KEYS[4], ARGV[1])
end
redis.call('INCRBY', KEYS[1], ARGV[2])
return tonumber(redis.call('GET', KEYS[1]))
"""


class RedisBudgetStore:
    def __init__(self, client: Any, prefix: str = "costpilot") -> None:
        self._client = client
        self._prefix = prefix
        self._reserve_script = client.register_script(RESERVE_LUA)
        self._reconcile_script = client.register_script(RECONCILE_LUA)

    def _keys(self, team: str) -> list[str]:
        base = f"{self._prefix}:{{{team}}}:budget"
        return [f"{base}:spent", f"{base}:reserved", f"{base}:amounts", f"{base}:expiries"]

    def reserve(
        self,
        team: str,
        reservation_id: str,
        amount_micro: int,
        limit_micro: int,
        now_ms: int,
        ttl_ms: int,
    ) -> ReserveOutcome:
        if amount_micro < 0 or limit_micro < 0:
            raise ValueError("montantes negativos não são válidos")
        accepted, spent, reserved = self._reserve_script(
            keys=self._keys(team),
            args=[limit_micro, amount_micro, reservation_id, now_ms, now_ms + ttl_ms],
        )
        return ReserveOutcome(bool(int(accepted)), int(spent), int(reserved))

    def reconcile(self, team: str, reservation_id: str, actual_micro: int) -> int:
        if actual_micro < 0:
            raise ValueError("o custo real não pode ser negativo")
        spent = self._reconcile_script(keys=self._keys(team), args=[reservation_id, actual_micro])
        return int(spent)

    def snapshot(self, team: str) -> BudgetSnapshot:
        spent_key, reserved_key, _, _ = self._keys(team)
        spent, reserved = self._client.mget([spent_key, reserved_key])
        return BudgetSnapshot(team, int(spent or 0), int(reserved or 0))

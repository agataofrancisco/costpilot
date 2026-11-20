"""Orçamento por equipa: reserva antes de cada tentativa, reconciliação depois.

Invariante: `spent + reserved <= limit` em todos os momentos, salvo quando uma reserva
expira antes de ser reconciliada (ver `reconcile`). Esta implementação em memória serve
para demo e testes; a versão de produção é `RedisBudgetStore` (atomicidade via Lua).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ReserveOutcome:
    accepted: bool
    spent_micro: int
    reserved_micro: int


@dataclass(frozen=True, slots=True)
class BudgetSnapshot:
    team: str
    spent_micro: int
    reserved_micro: int


class BudgetStore(Protocol):
    def reserve(
        self,
        team: str,
        reservation_id: str,
        amount_micro: int,
        limit_micro: int,
        now_ms: int,
        ttl_ms: int,
    ) -> ReserveOutcome: ...

    def reconcile(self, team: str, reservation_id: str, actual_micro: int) -> int: ...

    def snapshot(self, team: str) -> BudgetSnapshot: ...


@dataclass(slots=True)
class _TeamState:
    spent: int = 0
    reserved: int = 0
    reservations: dict[str, tuple[int, int]] | None = None

    def __post_init__(self) -> None:
        if self.reservations is None:
            self.reservations = {}


class InMemoryBudgetStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._teams: dict[str, _TeamState] = {}

    def _state(self, team: str) -> _TeamState:
        return self._teams.setdefault(team, _TeamState())

    def _purge_expired(self, state: _TeamState, now_ms: int) -> None:
        assert state.reservations is not None
        for rid, (amount, expires_at) in list(state.reservations.items()):
            if expires_at <= now_ms:
                state.reserved -= amount
                del state.reservations[rid]

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
        with self._lock:
            state = self._state(team)
            self._purge_expired(state, now_ms)
            if state.spent + state.reserved + amount_micro > limit_micro:
                return ReserveOutcome(False, state.spent, state.reserved)
            assert state.reservations is not None
            state.reserved += amount_micro
            state.reservations[reservation_id] = (amount_micro, now_ms + ttl_ms)
            return ReserveOutcome(True, state.spent, state.reserved)

    def reconcile(self, team: str, reservation_id: str, actual_micro: int) -> int:
        if actual_micro < 0:
            raise ValueError("o custo real não pode ser negativo")
        with self._lock:
            state = self._state(team)
            assert state.reservations is not None
            entry = state.reservations.pop(reservation_id, None)
            if entry is not None:
                state.reserved -= entry[0]
            state.spent += actual_micro
            return state.spent

    def snapshot(self, team: str) -> BudgetSnapshot:
        with self._lock:
            state = self._state(team)
            return BudgetSnapshot(team, state.spent, state.reserved)

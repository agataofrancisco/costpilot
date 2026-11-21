"""Armazenamento da cache de respostas com TTL. Memória para demo/testes, Redis em produção."""

from __future__ import annotations

import threading
import time
from typing import Any, Protocol


class ResponseCache(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str, ttl_seconds: int) -> None: ...


class MemoryResponseCache:
    def __init__(self, clock: Any = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._items: dict[str, tuple[str, float]] = {}

    def get(self, key: str) -> str | None:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            value, expires_at = item
            if expires_at <= self._clock():
                del self._items[key]
                return None
            return value

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        with self._lock:
            self._items[key] = (value, self._clock() + ttl_seconds)


class RedisResponseCache:
    def __init__(self, client: Any) -> None:
        self._client = client

    def get(self, key: str) -> str | None:
        raw = self._client.get(key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return None
        return raw if isinstance(raw, str) else None

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._client.set(key, value, ex=ttl_seconds)

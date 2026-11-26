from __future__ import annotations

import time
from collections.abc import Callable
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class TTLCache(Generic[K, V]):
    def __init__(
        self,
        ttl_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_entries: int = 128,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._max_entries = max(1, max_entries)
        self._store: dict[K, tuple[float, V]] = {}

    @property
    def enabled(self) -> bool:
        return self._ttl_seconds > 0

    def get(self, key: K) -> V | None:
        if not self.enabled:
            return None

        entry = self._store.get(key)
        if entry is None:
            return None

        expires_at, value = entry
        if self._clock() >= expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: K, value: V) -> None:
        if not self.enabled:
            return

        if len(self._store) >= self._max_entries:
            oldest_key = next(iter(self._store))
            self._store.pop(oldest_key, None)

        self._store[key] = (self._clock() + self._ttl_seconds, value)

    def clear(self) -> None:
        self._store.clear()

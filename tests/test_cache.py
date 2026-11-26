from __future__ import annotations

from maya_agent.tools.cache import TTLCache


def test_cache_returns_value_before_expiry() -> None:
    now = 0.0
    cache: TTLCache[str, str] = TTLCache(10, clock=lambda: now)

    cache.set("k", "v")

    assert cache.get("k") == "v"


def test_cache_expires_value() -> None:
    now = 0.0
    cache: TTLCache[str, str] = TTLCache(10, clock=lambda: now)

    cache.set("k", "v")
    now = 10

    assert cache.get("k") is None


def test_cache_disabled_when_ttl_is_zero() -> None:
    cache: TTLCache[str, str] = TTLCache(0)

    cache.set("k", "v")

    assert cache.get("k") is None
    assert cache.enabled is False


def test_cache_evicts_oldest_entry_at_capacity() -> None:
    cache: TTLCache[str, str] = TTLCache(10, max_entries=2)

    cache.set("a", "1")
    cache.set("b", "2")
    cache.set("c", "3")

    assert cache.get("a") is None
    assert cache.get("b") == "2"
    assert cache.get("c") == "3"


def test_cache_clear() -> None:
    cache: TTLCache[str, str] = TTLCache(10)
    cache.set("k", "v")

    cache.clear()

    assert cache.get("k") is None

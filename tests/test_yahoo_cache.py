"""In-memory Yahoo cache: hit, expiry, eviction, and a shared in-flight fetch.

Run: python tests/test_yahoo_cache.py
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yahoo_cache


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_hit_returns_the_stored_value():
    cache = yahoo_cache.TTLCache(max_entries=4, clock=Clock())
    cache.set("price", {"vz": 40}, ttl=30)
    assert cache.get("price") == {"vz": 40}
    # None is a real stored value, not a miss.
    cache.set("empty", None, ttl=30)
    assert cache.get("empty") is None
    assert cache.get("missing") is yahoo_cache.CACHE_MISS


def test_entry_expires_when_the_ttl_is_reached():
    clock = Clock()
    cache = yahoo_cache.TTLCache(max_entries=4, clock=clock)
    cache.set("info", {"quoteType": "EQUITY"}, ttl=10)
    clock.t = 9.9
    assert cache.get("info") == {"quoteType": "EQUITY"}
    clock.t = 10
    assert cache.get("info") is yahoo_cache.CACHE_MISS
    assert cache.get("info") is yahoo_cache.CACHE_MISS


def test_oldest_entry_is_evicted_when_full():
    clock = Clock()
    cache = yahoo_cache.TTLCache(max_entries=2, clock=clock)
    cache.set("a", 1, ttl=100)
    cache.set("b", 2, ttl=100)
    # Reading a makes it the newest, so the next insert drops b.
    assert cache.get("a") == 1
    cache.set("c", 3, ttl=100)
    assert cache.get("b") is yahoo_cache.CACHE_MISS
    assert cache.get("a") == 1
    assert cache.get("c") == 3
    assert len(cache) == 2

    # An expired entry does not keep its slot.
    clock.t = 1000
    cache.set("d", 4, ttl=5)
    assert cache.get("a") is yahoo_cache.CACHE_MISS
    assert cache.get("c") is yahoo_cache.CACHE_MISS
    assert cache.get("d") == 4
    assert len(cache) == 1


def test_fresh_load_bypasses_and_replaces_the_cached_value():
    yahoo_cache.clear_market_cache()
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return calls["n"]

    assert yahoo_cache.cached_load("quote", 60, loader) == 1
    assert yahoo_cache.cached_load("quote", 60, loader) == 1
    assert calls["n"] == 1
    assert yahoo_cache.cached_load("quote", 60, loader, fresh=True) == 2
    assert yahoo_cache.cached_load("quote", 60, loader) == 2
    assert calls["n"] == 2


def test_failed_load_is_not_cached_and_rate_limit_is_retried():
    yahoo_cache.clear_market_cache()
    calls = {"n": 0}
    original = yahoo_cache._backoff
    yahoo_cache._backoff = lambda attempt: None
    try:
        def fail():
            calls["n"] += 1
            raise RuntimeError("permanent")

        try:
            yahoo_cache.cached_load("bad", 60, fail)
            raise AssertionError("permanent errors must surface")
        except RuntimeError:
            pass
        try:
            yahoo_cache.cached_load("bad", 60, fail)
        except RuntimeError:
            pass
        assert calls["n"] == 2

        limited_calls = {"n": 0}

        def limited():
            limited_calls["n"] += 1
            if limited_calls["n"] < 3:
                raise yahoo_cache.YFRateLimitError()
            return "ok"

        assert yahoo_cache.cached_load("limited", 60, limited) == "ok"
        # Two rate-limit failures, then the successful attempt. The stored
        # value is served after that, so the loader does not run again.
        assert limited_calls["n"] == 3
        assert yahoo_cache.cached_load("limited", 60, limited) == "ok"
        assert limited_calls["n"] == 3
    finally:
        yahoo_cache._backoff = original
        yahoo_cache.clear_market_cache()


def test_concurrent_callers_share_one_fetch():
    yahoo_cache.clear_market_cache()
    calls = {"n": 0}
    gate = threading.Event()

    def loader():
        calls["n"] += 1
        gate.wait(2)
        return "shared"

    results = []
    errors = []

    def run():
        try:
            results.append(yahoo_cache.cached_load("shared", 60, loader))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(8)]
    for thread in threads:
        thread.start()
    time.sleep(0.05)
    gate.set()
    for thread in threads:
        thread.join(2)
    assert errors == []
    assert results == ["shared"] * 8
    assert calls["n"] == 1
    yahoo_cache.clear_market_cache()


def test_concurrent_sets_stay_within_the_cap():
    cache = yahoo_cache.TTLCache(max_entries=32)
    errors = []

    def worker(i):
        try:
            for j in range(40):
                cache.set((i, j), i + j, ttl=30)
                cache.get((i, j))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)
    assert errors == []
    assert len(cache) <= 32


if __name__ == "__main__":
    test_hit_returns_the_stored_value()
    test_entry_expires_when_the_ttl_is_reached()
    test_oldest_entry_is_evicted_when_full()
    test_fresh_load_bypasses_and_replaces_the_cached_value()
    test_failed_load_is_not_cached_and_rate_limit_is_retried()
    test_concurrent_callers_share_one_fetch()
    test_concurrent_sets_stay_within_the_cap()
    print("All Yahoo cache tests passed.")

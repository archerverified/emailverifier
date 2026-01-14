"""Tests for catch-all domain cache functionality."""

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

sys.path.insert(0, ".")
from catch_all_cache import CatchAllCache


class TestCatchAllCacheBasics:
    """Basic cache functionality tests."""

    def test_cache_miss_returns_none(self) -> None:
        """Cache returns None for uncached domains."""
        cache = CatchAllCache(ttl_minutes=60)
        assert cache.get("example.com") is None

    def test_cache_hit_returns_value(self) -> None:
        """Cache returns stored value for cached domains."""
        cache = CatchAllCache(ttl_minutes=60)
        cache.set("example.com", True)
        assert cache.get("example.com") is True

        cache.set("notcatchall.com", False)
        assert cache.get("notcatchall.com") is False

    def test_cache_is_case_insensitive(self) -> None:
        """Domain lookups are case-insensitive."""
        cache = CatchAllCache(ttl_minutes=60)
        cache.set("Example.COM", True)
        assert cache.get("example.com") is True
        assert cache.get("EXAMPLE.COM") is True
        assert cache.get("ExAmPlE.cOm") is True

    def test_cache_size(self) -> None:
        """Size method returns correct count."""
        cache = CatchAllCache(ttl_minutes=60)
        assert cache.size() == 0

        cache.set("a.com", True)
        assert cache.size() == 1

        cache.set("b.com", False)
        assert cache.size() == 2

        # Same domain (case-insensitive) doesn't increase count
        cache.set("A.COM", True)
        assert cache.size() == 2

    def test_cache_clear(self) -> None:
        """Clear removes all entries."""
        cache = CatchAllCache(ttl_minutes=60)
        cache.set("a.com", True)
        cache.set("b.com", False)
        assert cache.size() == 2

        cache.clear()
        assert cache.size() == 0
        assert cache.get("a.com") is None


class TestCatchAllCacheTTL:
    """TTL expiration tests."""

    def test_entry_expires_after_ttl(self) -> None:
        """Cached entries expire after TTL."""
        # Use 1 second TTL for fast testing
        cache = CatchAllCache(ttl_minutes=1)
        # Override ttl_seconds directly for faster test
        cache.ttl_seconds = 0.1  # 100ms

        cache.set("example.com", True)
        assert cache.get("example.com") is True

        # Wait for expiration
        time.sleep(0.15)
        assert cache.get("example.com") is None

    def test_clear_expired_removes_old_entries(self) -> None:
        """clear_expired removes only expired entries."""
        cache = CatchAllCache(ttl_minutes=1)
        cache.ttl_seconds = 0.1  # 100ms

        cache.set("old.com", True)
        time.sleep(0.15)  # Let old.com expire

        cache.set("new.com", False)  # This one is fresh

        removed = cache.clear_expired()
        assert removed == 1
        assert cache.get("old.com") is None
        assert cache.get("new.com") is False
        assert cache.size() == 1

    def test_ttl_is_configurable(self) -> None:
        """TTL can be configured via constructor."""
        cache_short = CatchAllCache(ttl_minutes=1)
        assert cache_short.ttl_seconds == 60

        cache_long = CatchAllCache(ttl_minutes=1440)
        assert cache_long.ttl_seconds == 86400


class TestCatchAllCacheThreadSafety:
    """Thread safety tests."""

    def test_concurrent_reads_and_writes(self) -> None:
        """Cache handles concurrent reads and writes safely."""
        cache = CatchAllCache(ttl_minutes=60)
        domains = [f"domain{i}.com" for i in range(100)]
        errors: list[Exception] = []

        def writer() -> None:
            try:
                for i, domain in enumerate(domains):
                    cache.set(domain, i % 2 == 0)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def reader() -> None:
            try:
                for domain in domains:
                    _ = cache.get(domain)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = []
        for _ in range(5):
            threads.append(threading.Thread(target=writer))
            threads.append(threading.Thread(target=reader))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread errors: {errors}"

    def test_concurrent_clear_expired(self) -> None:
        """clear_expired is thread-safe."""
        cache = CatchAllCache(ttl_minutes=1)
        cache.ttl_seconds = 0.05  # 50ms

        errors: list[Exception] = []

        def populate_and_expire() -> None:
            try:
                for i in range(50):
                    cache.set(f"domain{i}.com", True)
                time.sleep(0.1)  # Let entries expire
                cache.clear_expired()
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(populate_and_expire) for _ in range(10)]
            for f in futures:
                f.result()

        assert len(errors) == 0, f"Thread errors: {errors}"

    def test_no_race_condition_on_get_after_set(self) -> None:
        """Set followed by get returns correct value under concurrent load."""
        cache = CatchAllCache(ttl_minutes=60)
        results: dict[str, bool | None] = {}
        lock = threading.Lock()

        def set_and_get(domain: str, value: bool) -> None:
            cache.set(domain, value)
            result = cache.get(domain)
            with lock:
                results[domain] = result

        threads = []
        for i in range(100):
            domain = f"test{i}.com"
            value = i % 2 == 0
            t = threading.Thread(target=set_and_get, args=(domain, value))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # All results should match what was set
        for i in range(100):
            domain = f"test{i}.com"
            expected = i % 2 == 0
            assert results[domain] == expected, f"Mismatch for {domain}"


class TestCatchAllCacheEdgeCases:
    """Edge case tests."""

    def test_empty_domain(self) -> None:
        """Empty domain string is handled."""
        cache = CatchAllCache(ttl_minutes=60)
        cache.set("", True)
        assert cache.get("") is True

    def test_overwrite_existing_entry(self) -> None:
        """Setting same domain overwrites previous value."""
        cache = CatchAllCache(ttl_minutes=60)
        cache.set("example.com", True)
        assert cache.get("example.com") is True

        cache.set("example.com", False)
        assert cache.get("example.com") is False

    def test_very_long_ttl(self) -> None:
        """Very long TTL works correctly."""
        cache = CatchAllCache(ttl_minutes=10080)  # 1 week
        assert cache.ttl_seconds == 604800

        cache.set("example.com", True)
        assert cache.get("example.com") is True

    def test_expired_entry_removed_on_get(self) -> None:
        """Expired entries are removed when accessed via get."""
        cache = CatchAllCache(ttl_minutes=1)
        cache.ttl_seconds = 0.05  # 50ms

        cache.set("example.com", True)
        assert cache.size() == 1

        time.sleep(0.1)  # Let it expire

        # Get should return None AND remove the entry
        assert cache.get("example.com") is None
        # Entry should be removed from cache
        assert cache.size() == 0

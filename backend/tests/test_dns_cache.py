"""
Tests for DNS cache functionality.
"""

import os
import sys
import threading
import time

# Ensure parent directory is in path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dns_cache import DNSCache  # noqa: E402


class TestDNSCacheBasics:
    """Test basic DNS cache operations."""

    def test_cache_miss_returns_none(self) -> None:
        """Cache miss should return None."""
        cache = DNSCache(ttl_minutes=30)
        result = cache.get_mx("unknown-domain.com")
        assert result is None

    def test_cache_set_and_get(self) -> None:
        """Setting and getting a value should work."""
        cache = DNSCache(ttl_minutes=30)
        mx_records = ["mx1.example.com", "mx2.example.com"]

        cache.set_mx("example.com", mx_records)
        result = cache.get_mx("example.com")

        assert result == mx_records

    def test_cache_is_case_insensitive(self) -> None:
        """Domain lookups should be case-insensitive."""
        cache = DNSCache(ttl_minutes=30)
        mx_records = ["mx.example.com"]

        cache.set_mx("EXAMPLE.COM", mx_records)

        assert cache.get_mx("example.com") == mx_records
        assert cache.get_mx("Example.Com") == mx_records
        assert cache.get_mx("EXAMPLE.COM") == mx_records

    def test_cache_negative_result(self) -> None:
        """Caching negative results (no MX) should work."""
        cache = DNSCache(ttl_minutes=30)

        cache.set_negative("no-mx-domain.com")
        result = cache.get_mx("no-mx-domain.com")

        assert result == []

    def test_cache_clear(self) -> None:
        """Clearing the cache should remove all entries."""
        cache = DNSCache(ttl_minutes=30)
        cache.set_mx("example.com", ["mx.example.com"])
        cache.set_mx("test.com", ["mx.test.com"])

        assert cache.size() == 2

        cache.clear()

        assert cache.size() == 0
        assert cache.get_mx("example.com") is None
        assert cache.get_mx("test.com") is None

    def test_cache_size(self) -> None:
        """Size should reflect number of cached entries."""
        cache = DNSCache(ttl_minutes=30)

        assert cache.size() == 0

        cache.set_mx("a.com", ["mx.a.com"])
        assert cache.size() == 1

        cache.set_mx("b.com", ["mx.b.com"])
        assert cache.size() == 2

        # Updating existing entry shouldn't increase size
        cache.set_mx("a.com", ["mx2.a.com"])
        assert cache.size() == 2


class TestDNSCacheTTL:
    """Test TTL (time-to-live) expiration."""

    def test_entry_expires_after_ttl(self) -> None:
        """Entry should expire after TTL."""
        # Use a very short TTL for testing (1 second = 1/60 minute)
        cache = DNSCache(ttl_minutes=1 / 60)  # ~1 second TTL

        cache.set_mx("example.com", ["mx.example.com"])
        assert cache.get_mx("example.com") == ["mx.example.com"]

        # Wait for expiration
        time.sleep(1.5)

        # Should be expired now
        result = cache.get_mx("example.com")
        assert result is None

    def test_fresh_entry_not_expired(self) -> None:
        """Fresh entry should not be expired."""
        cache = DNSCache(ttl_minutes=60)  # 1 hour TTL

        cache.set_mx("example.com", ["mx.example.com"])

        # Should still be valid
        result = cache.get_mx("example.com")
        assert result == ["mx.example.com"]

    def test_get_stats_counts_expired(self) -> None:
        """Stats should count expired entries."""
        cache = DNSCache(ttl_minutes=1 / 60)  # ~1 second TTL

        cache.set_mx("example.com", ["mx.example.com"])

        stats = cache.get_stats()
        assert stats["cache_size"] == 1
        assert stats["expired_count"] == 0

        # Wait for expiration
        time.sleep(1.5)

        stats = cache.get_stats()
        assert stats["cache_size"] == 1  # Still in cache until accessed
        assert stats["expired_count"] == 1


class TestDNSCacheThreadSafety:
    """Test thread safety of the DNS cache."""

    def test_concurrent_reads_and_writes(self) -> None:
        """Multiple threads reading and writing should not corrupt data."""
        cache = DNSCache(ttl_minutes=30)
        errors: list[str] = []
        iterations = 100

        def writer(domain: str) -> None:
            for i in range(iterations):
                try:
                    cache.set_mx(domain, [f"mx{i}.{domain}"])
                except Exception as e:
                    errors.append(f"Writer error: {e}")

        def reader(domain: str) -> None:
            for _ in range(iterations):
                try:
                    result = cache.get_mx(domain)
                    # Result should be None or a valid list
                    if result is not None and not isinstance(result, list):
                        errors.append(f"Invalid result type: {type(result)}")
                except Exception as e:
                    errors.append(f"Reader error: {e}")

        # Create threads for different domains
        threads = []
        for domain in ["a.com", "b.com", "c.com"]:
            threads.append(threading.Thread(target=writer, args=(domain,)))
            threads.append(threading.Thread(target=reader, args=(domain,)))

        # Start all threads
        for t in threads:
            t.start()

        # Wait for all threads
        for t in threads:
            t.join()

        assert errors == [], f"Thread safety errors: {errors}"

    def test_concurrent_clear(self) -> None:
        """Clearing while reading/writing should not cause errors."""
        cache = DNSCache(ttl_minutes=30)
        errors: list[str] = []
        iterations = 50

        def writer() -> None:
            for i in range(iterations):
                try:
                    cache.set_mx(f"domain{i}.com", [f"mx.domain{i}.com"])
                except Exception as e:
                    errors.append(f"Writer error: {e}")

        def clearer() -> None:
            for _ in range(iterations // 10):
                try:
                    cache.clear()
                    time.sleep(0.01)
                except Exception as e:
                    errors.append(f"Clearer error: {e}")

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=writer),
            threading.Thread(target=clearer),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread safety errors: {errors}"


class TestDNSCacheEdgeCases:
    """Test edge cases."""

    def test_empty_mx_list(self) -> None:
        """Caching empty MX list should work."""
        cache = DNSCache(ttl_minutes=30)

        cache.set_mx("example.com", [])
        result = cache.get_mx("example.com")

        assert result == []

    def test_overwrite_entry(self) -> None:
        """Overwriting an entry should update the value and timestamp."""
        cache = DNSCache(ttl_minutes=1 / 60)  # Short TTL

        cache.set_mx("example.com", ["old-mx.example.com"])
        time.sleep(0.5)

        # Overwrite with new value
        cache.set_mx("example.com", ["new-mx.example.com"])

        # Should get new value
        result = cache.get_mx("example.com")
        assert result == ["new-mx.example.com"]

        # Should have fresh timestamp (not expired)
        time.sleep(0.7)  # Total > 1s since first set, but < 1s since overwrite
        result = cache.get_mx("example.com")
        assert result == ["new-mx.example.com"]

    def test_unicode_domain(self) -> None:
        """Unicode domains should work."""
        cache = DNSCache(ttl_minutes=30)

        # IDN domain
        cache.set_mx("münchen.de", ["mx.münchen.de"])
        result = cache.get_mx("münchen.de")

        assert result == ["mx.münchen.de"]

    def test_very_long_mx_list(self) -> None:
        """Very long MX list should work."""
        cache = DNSCache(ttl_minutes=30)

        mx_records = [f"mx{i}.example.com" for i in range(100)]
        cache.set_mx("example.com", mx_records)

        result = cache.get_mx("example.com")
        assert result == mx_records
        assert len(result) == 100

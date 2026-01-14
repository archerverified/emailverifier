"""
Thread-safe DNS/MX cache with TTL for improved email verification performance.
Caches MX records at process-lifetime scope with configurable expiration.
"""

import threading
import time


class DNSCache:
    """Thread-safe DNS MX record cache with TTL expiration."""

    def __init__(self, ttl_minutes: int = 30):
        """
        Initialize the DNS cache.

        Args:
            ttl_minutes: Time-to-live for cached entries in minutes.
        """
        self._cache: dict[str, tuple[list[str], float]] = {}
        self._lock = threading.Lock()
        self._ttl_seconds = ttl_minutes * 60

    def get_mx(self, domain: str) -> list[str] | None:
        """
        Get cached MX records for a domain if not expired.

        Args:
            domain: The domain to look up.

        Returns:
            List of MX hostnames if cached and valid, None if not cached or expired.
        """
        domain_lower = domain.lower()
        with self._lock:
            if domain_lower not in self._cache:
                return None

            mx_records, timestamp = self._cache[domain_lower]
            if time.time() - timestamp > self._ttl_seconds:
                # Expired, remove from cache
                del self._cache[domain_lower]
                return None

            return mx_records

    def set_mx(self, domain: str, mx_records: list[str]) -> None:
        """
        Cache MX records for a domain with current timestamp.

        Args:
            domain: The domain to cache records for.
            mx_records: List of MX hostnames to cache.
        """
        domain_lower = domain.lower()
        with self._lock:
            self._cache[domain_lower] = (mx_records, time.time())

    def set_negative(self, domain: str) -> None:
        """
        Cache a negative result (no MX records found) for a domain.

        Args:
            domain: The domain with no MX records.
        """
        domain_lower = domain.lower()
        with self._lock:
            self._cache[domain_lower] = ([], time.time())

    def clear(self) -> None:
        """Clear all cached entries (primarily for testing)."""
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        """Return the number of cached entries."""
        with self._lock:
            return len(self._cache)

    def get_stats(self) -> dict[str, int]:
        """
        Get cache statistics for monitoring.

        Returns:
            Dict with cache_size and expired_count.
        """
        with self._lock:
            current_time = time.time()
            expired_count = sum(
                1
                for _, (_, timestamp) in self._cache.items()
                if current_time - timestamp > self._ttl_seconds
            )
            return {
                "cache_size": len(self._cache),
                "expired_count": expired_count,
            }

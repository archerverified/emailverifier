"""
Thread-safe catch-all domain cache with TTL.
Caches whether a domain accepts all emails (catch-all) to avoid redundant SMTP checks.
"""

import threading
import time


class CatchAllCache:
    """
    Thread-safe cache for catch-all domain detection results.

    Features:
    - TTL-based expiration
    - Thread-safe with internal lock
    - Memory-efficient (stores only domain -> (bool, timestamp))
    """

    def __init__(self, ttl_minutes: int = 1440):
        """
        Initialize cache with TTL.

        Args:
            ttl_minutes: Time-to-live for cache entries (default 24 hours)
        """
        self._cache: dict[str, tuple[bool, float]] = {}  # domain -> (is_catch_all, checked_at)
        self._lock = threading.Lock()
        self.ttl_seconds = ttl_minutes * 60

    def get(self, domain: str) -> bool | None:
        """
        Get cached catch-all status for a domain.

        Args:
            domain: Domain to lookup

        Returns:
            True if domain is catch-all, False if not, None if not cached or expired
        """
        domain_lower = domain.lower()
        with self._lock:
            entry = self._cache.get(domain_lower)
            if entry is None:
                return None

            is_catch_all, checked_at = entry
            if time.monotonic() - checked_at > self.ttl_seconds:
                # Expired - remove and return None
                del self._cache[domain_lower]
                return None

            return is_catch_all

    def set(self, domain: str, is_catch_all: bool) -> None:
        """
        Store catch-all status for a domain.

        Args:
            domain: Domain to cache
            is_catch_all: Whether the domain accepts all emails
        """
        domain_lower = domain.lower()
        with self._lock:
            self._cache[domain_lower] = (is_catch_all, time.monotonic())

    def clear_expired(self) -> int:
        """
        Remove all expired entries from cache.

        Returns:
            Number of entries removed
        """
        now = time.monotonic()
        removed = 0
        with self._lock:
            expired_domains = [
                domain
                for domain, (_, checked_at) in self._cache.items()
                if now - checked_at > self.ttl_seconds
            ]
            for domain in expired_domains:
                del self._cache[domain]
                removed += 1
        return removed

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        """Get number of entries in cache."""
        with self._lock:
            return len(self._cache)

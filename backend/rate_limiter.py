"""
Simple in-memory rate limiter for the Lead Validator API.
Supports dual-strategy limiting: per-IP and per-API-key.

Thread-safe implementation suitable for single-VPS deployment.
"""

import time
from collections import defaultdict
from threading import Lock


class RateLimiter:
    """
    Thread-safe rate limiter with sliding window algorithm.

    Tracks requests per IP and per API key with configurable limits.
    """

    def __init__(self) -> None:
        self._ip_requests: dict[str, list[float]] = defaultdict(list)
        self._key_requests: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def _cleanup_old(self, now: float, window: int) -> None:
        """Remove timestamps older than the window. Must be called with lock held."""
        cutoff = now - window

        # Clean IP requests
        for ip in list(self._ip_requests.keys()):
            self._ip_requests[ip] = [t for t in self._ip_requests[ip] if t > cutoff]
            if not self._ip_requests[ip]:
                del self._ip_requests[ip]

        # Clean API key requests
        for key in list(self._key_requests.keys()):
            self._key_requests[key] = [t for t in self._key_requests[key] if t > cutoff]
            if not self._key_requests[key]:
                del self._key_requests[key]

    def is_allowed(
        self,
        ip: str,
        api_key: str | None = None,
        ip_limit: int = 10,
        key_limit: int = 100,
        window: int = 60,
    ) -> tuple[bool, str, dict[str, int]]:
        """
        Check if a request is allowed under rate limits.

        Args:
            ip: Client IP address
            api_key: API key (optional)
            ip_limit: Max requests per IP per window
            key_limit: Max requests per API key per window
            window: Time window in seconds

        Returns:
            Tuple of (allowed, reason, details)
            - allowed: True if request is permitted
            - reason: Empty string if allowed, otherwise explanation
            - details: Dict with current counts and limits
        """
        now = time.time()

        with self._lock:
            # Clean old entries first
            self._cleanup_old(now, window)

            # Get current counts
            ip_count = len(self._ip_requests[ip])
            key_count = len(self._key_requests[api_key]) if api_key else 0

            details = {
                "ip_requests": ip_count,
                "ip_limit": ip_limit,
                "window_seconds": window,
            }

            if api_key:
                details["key_requests"] = key_count
                details["key_limit"] = key_limit

            # Check IP limit
            if ip_count >= ip_limit:
                return (
                    False,
                    f"IP rate limit exceeded ({ip_limit} requests per {window}s)",
                    details,
                )

            # Check API key limit (if key provided)
            if api_key and key_count >= key_limit:
                return (
                    False,
                    f"API key rate limit exceeded ({key_limit} requests per {window}s)",
                    details,
                )

            # Record this request
            self._ip_requests[ip].append(now)
            if api_key:
                self._key_requests[api_key].append(now)

            # Update counts after recording
            details["ip_requests"] = ip_count + 1
            if api_key:
                details["key_requests"] = key_count + 1

            return True, "", details

    def get_stats(self) -> dict[str, int]:
        """Get current rate limiter statistics."""
        with self._lock:
            return {
                "tracked_ips": len(self._ip_requests),
                "tracked_keys": len(self._key_requests),
                "total_ip_entries": sum(len(v) for v in self._ip_requests.values()),
                "total_key_entries": sum(len(v) for v in self._key_requests.values()),
            }

    def clear(self) -> None:
        """Clear all tracked requests (for testing)."""
        with self._lock:
            self._ip_requests.clear()
            self._key_requests.clear()


# Global rate limiter instance
rate_limiter = RateLimiter()

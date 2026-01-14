"""
Tests for rate limiting functionality.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rate_limiter import RateLimiter  # noqa: E402


class TestRateLimiterBasics:
    """Test basic rate limiter operations."""

    def test_first_request_allowed(self) -> None:
        """First request should always be allowed."""
        limiter = RateLimiter()
        allowed, reason, details = limiter.is_allowed("192.168.1.1")

        assert allowed is True
        assert reason == ""
        assert details["ip_requests"] == 1

    def test_requests_within_limit_allowed(self) -> None:
        """Requests within limit should be allowed."""
        limiter = RateLimiter()

        for i in range(10):
            allowed, reason, _ = limiter.is_allowed("192.168.1.1", ip_limit=10)
            assert allowed is True, f"Request {i+1} should be allowed"

    def test_requests_exceeding_limit_blocked(self) -> None:
        """Requests exceeding limit should be blocked."""
        limiter = RateLimiter()

        # Make 10 requests (at limit)
        for _ in range(10):
            allowed, _, _ = limiter.is_allowed("192.168.1.1", ip_limit=10)
            assert allowed is True

        # 11th request should be blocked
        allowed, reason, details = limiter.is_allowed("192.168.1.1", ip_limit=10)
        assert allowed is False
        assert "IP rate limit exceeded" in reason
        assert details["ip_requests"] == 10
        assert details["ip_limit"] == 10

    def test_different_ips_have_separate_limits(self) -> None:
        """Different IPs should have independent limits."""
        limiter = RateLimiter()

        # Exhaust limit for IP 1
        for _ in range(10):
            limiter.is_allowed("192.168.1.1", ip_limit=10)

        # IP 1 should be blocked
        allowed1, _, _ = limiter.is_allowed("192.168.1.1", ip_limit=10)
        assert allowed1 is False

        # IP 2 should still be allowed
        allowed2, _, _ = limiter.is_allowed("192.168.1.2", ip_limit=10)
        assert allowed2 is True


class TestAPIKeyLimiting:
    """Test API key rate limiting."""

    def test_api_key_limit_tracked_separately(self) -> None:
        """API key limit should be tracked separately from IP."""
        limiter = RateLimiter()

        # Make requests with API key
        for i in range(5):
            allowed, _, details = limiter.is_allowed(
                "192.168.1.1", api_key="key123", ip_limit=10, key_limit=100
            )
            assert allowed is True
            assert details["key_requests"] == i + 1

    def test_api_key_limit_exceeded(self) -> None:
        """Should block when API key limit is exceeded."""
        limiter = RateLimiter()

        # Exhaust API key limit
        for _ in range(5):
            limiter.is_allowed("192.168.1.1", api_key="key123", ip_limit=100, key_limit=5)

        # Next request with same key should be blocked
        allowed, reason, _ = limiter.is_allowed(
            "192.168.1.1", api_key="key123", ip_limit=100, key_limit=5
        )
        assert allowed is False
        assert "API key rate limit exceeded" in reason

    def test_different_api_keys_have_separate_limits(self) -> None:
        """Different API keys should have independent limits."""
        limiter = RateLimiter()

        # Exhaust limit for key1
        for _ in range(5):
            limiter.is_allowed("192.168.1.1", api_key="key1", ip_limit=100, key_limit=5)

        # Key1 should be blocked
        allowed1, _, _ = limiter.is_allowed(
            "192.168.1.1", api_key="key1", ip_limit=100, key_limit=5
        )
        assert allowed1 is False

        # Key2 should still be allowed
        allowed2, _, _ = limiter.is_allowed(
            "192.168.1.1", api_key="key2", ip_limit=100, key_limit=5
        )
        assert allowed2 is True


class TestWindowExpiration:
    """Test time window expiration."""

    def test_requests_expire_after_window(self) -> None:
        """Requests should expire after the time window."""
        limiter = RateLimiter()

        # Make requests up to limit
        for _ in range(5):
            limiter.is_allowed("192.168.1.1", ip_limit=5, window=1)

        # Should be blocked
        allowed, _, _ = limiter.is_allowed("192.168.1.1", ip_limit=5, window=1)
        assert allowed is False

        # Wait for window to expire
        time.sleep(1.2)

        # Should be allowed again
        allowed, _, _ = limiter.is_allowed("192.168.1.1", ip_limit=5, window=1)
        assert allowed is True


class TestClear:
    """Test clearing the rate limiter."""

    def test_clear_removes_all_entries(self) -> None:
        """Clear should remove all tracked requests."""
        limiter = RateLimiter()

        # Make some requests
        for _ in range(5):
            limiter.is_allowed("192.168.1.1", ip_limit=5)

        # Should be blocked
        allowed, _, _ = limiter.is_allowed("192.168.1.1", ip_limit=5)
        assert allowed is False

        # Clear limiter
        limiter.clear()

        # Should be allowed again
        allowed, _, _ = limiter.is_allowed("192.168.1.1", ip_limit=5)
        assert allowed is True


class TestStats:
    """Test rate limiter statistics."""

    def test_get_stats(self) -> None:
        """Should return correct statistics."""
        limiter = RateLimiter()

        # Make requests from different IPs and keys
        limiter.is_allowed("192.168.1.1", api_key="key1")
        limiter.is_allowed("192.168.1.2", api_key="key1")
        limiter.is_allowed("192.168.1.3", api_key="key2")

        stats = limiter.get_stats()
        assert stats["tracked_ips"] == 3
        assert stats["tracked_keys"] == 2
        assert stats["total_ip_entries"] == 3
        assert stats["total_key_entries"] == 3

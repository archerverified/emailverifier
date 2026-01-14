"""
Tests for SMTP concurrency control (global and per-domain semaphores).
"""

import os
import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSMTPConcurrencyControl:
    """Test SMTP concurrency limiting via semaphores."""

    def test_get_domain_semaphore_creates_new(self) -> None:
        """get_domain_semaphore should create a new semaphore for unknown domain."""
        # Import here to avoid module-level import issues
        import app

        # Clear existing semaphores for clean test
        with app.domain_semaphores_lock:
            app.domain_semaphores.clear()

        sem = app.get_domain_semaphore("newdomain.com")

        assert sem is not None
        assert isinstance(sem, threading.Semaphore)

    def test_get_domain_semaphore_returns_same(self) -> None:
        """get_domain_semaphore should return the same semaphore for same domain."""
        import app

        with app.domain_semaphores_lock:
            app.domain_semaphores.clear()

        sem1 = app.get_domain_semaphore("example.com")
        sem2 = app.get_domain_semaphore("example.com")

        assert sem1 is sem2

    def test_get_domain_semaphore_case_insensitive(self) -> None:
        """get_domain_semaphore should be case-insensitive."""
        import app

        with app.domain_semaphores_lock:
            app.domain_semaphores.clear()

        sem1 = app.get_domain_semaphore("EXAMPLE.COM")
        sem2 = app.get_domain_semaphore("example.com")
        sem3 = app.get_domain_semaphore("Example.Com")

        assert sem1 is sem2
        assert sem2 is sem3

    def test_different_domains_get_different_semaphores(self) -> None:
        """Different domains should get different semaphores."""
        import app

        with app.domain_semaphores_lock:
            app.domain_semaphores.clear()

        sem1 = app.get_domain_semaphore("domain1.com")
        sem2 = app.get_domain_semaphore("domain2.com")

        assert sem1 is not sem2


class TestSemaphoreRelease:
    """Test that semaphores are properly released."""

    def test_semaphore_released_on_success(self) -> None:
        """Semaphore should be released after successful check."""
        import app

        # Get initial semaphore state
        sem = app.get_domain_semaphore("release-test.com")

        # Acquire and immediately release to get baseline
        sem.acquire()
        sem.release()

        # The semaphore should still be acquirable
        acquired = sem.acquire(blocking=False)
        assert acquired, "Semaphore should be acquirable"
        sem.release()

    def test_semaphore_released_on_exception(self) -> None:
        """Semaphore should be released even if exception occurs."""
        import app

        sem = app.get_domain_semaphore("exception-test.com")

        def code_that_raises() -> None:
            with sem:
                raise ValueError("Test exception")

        with pytest.raises(ValueError):
            code_that_raises()

        # Semaphore should still be usable
        acquired = sem.acquire(blocking=False)
        assert acquired, "Semaphore should be released after exception"
        sem.release()


class TestConcurrencyLimits:
    """Test that concurrency limits are enforced."""

    def test_global_semaphore_limits_concurrent_checks(self) -> None:
        """Global semaphore should limit total concurrent SMTP checks."""
        import app
        from config import Config

        # Track concurrent access
        max_concurrent = 0
        current_concurrent = 0
        lock = threading.Lock()

        def simulated_smtp_check() -> None:
            nonlocal max_concurrent, current_concurrent

            with app.smtp_global_semaphore:
                with lock:
                    current_concurrent += 1
                    max_concurrent = max(max_concurrent, current_concurrent)

                # Simulate work
                time.sleep(0.05)

                with lock:
                    current_concurrent -= 1

        # Create more threads than the limit
        num_threads = Config.SMTP_GLOBAL_WORKERS + 5
        threads = [threading.Thread(target=simulated_smtp_check) for _ in range(num_threads)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Max concurrent should not exceed the limit
        assert (
            max_concurrent <= Config.SMTP_GLOBAL_WORKERS
        ), f"Max concurrent {max_concurrent} exceeded limit {Config.SMTP_GLOBAL_WORKERS}"

    def test_per_domain_semaphore_limits_concurrent_checks(self) -> None:
        """Per-domain semaphore should limit concurrent checks per domain."""
        import app
        from config import Config

        with app.domain_semaphores_lock:
            app.domain_semaphores.clear()

        # Track concurrent access per domain
        domain = "limit-test.com"
        max_concurrent = 0
        current_concurrent = 0
        lock = threading.Lock()

        def simulated_smtp_check() -> None:
            nonlocal max_concurrent, current_concurrent

            domain_sem = app.get_domain_semaphore(domain)
            with domain_sem:
                with lock:
                    current_concurrent += 1
                    max_concurrent = max(max_concurrent, current_concurrent)

                # Simulate work
                time.sleep(0.05)

                with lock:
                    current_concurrent -= 1

        # Create more threads than the per-domain limit
        num_threads = Config.SMTP_PER_DOMAIN_LIMIT + 5
        threads = [threading.Thread(target=simulated_smtp_check) for _ in range(num_threads)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Max concurrent should not exceed the per-domain limit
        assert (
            max_concurrent <= Config.SMTP_PER_DOMAIN_LIMIT
        ), f"Max concurrent {max_concurrent} exceeded limit {Config.SMTP_PER_DOMAIN_LIMIT}"

    def test_different_domains_can_run_concurrently(self) -> None:
        """Different domains should be able to run concurrently."""
        import app

        with app.domain_semaphores_lock:
            app.domain_semaphores.clear()

        domains = ["domain1.com", "domain2.com", "domain3.com"]
        results: dict[str, bool] = {}
        lock = threading.Lock()

        def check_domain(domain: str) -> None:
            domain_sem = app.get_domain_semaphore(domain)
            with domain_sem:
                # Simulate work
                time.sleep(0.1)
                with lock:
                    results[domain] = True

        threads = [threading.Thread(target=check_domain, args=(d,)) for d in domains]

        start_time = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.time() - start_time

        # All domains should have completed
        assert len(results) == 3

        # Should have run concurrently (elapsed < sequential time)
        # Sequential would be ~0.3s, concurrent should be ~0.1s
        assert elapsed < 0.25, f"Elapsed {elapsed}s suggests domains didn't run concurrently"


class TestJitteredBackoff:
    """Test the jittered backoff function."""

    def test_jittered_backoff_returns_float(self) -> None:
        """_jittered_backoff should return a float."""
        import app

        result = app._jittered_backoff()
        assert isinstance(result, float)

    def test_jittered_backoff_has_variation(self) -> None:
        """_jittered_backoff should produce varied results (jitter)."""
        import app

        results = [app._jittered_backoff() for _ in range(20)]

        # Should have some variation (not all identical)
        unique_results = set(results)
        assert len(unique_results) > 1, "Jittered backoff should produce varied results"

    def test_jittered_backoff_minimum(self) -> None:
        """_jittered_backoff should never return less than minimum."""
        import app

        for _ in range(100):
            result = app._jittered_backoff()
            # Minimum is 100ms = 0.1s
            assert result >= 0.1, f"Backoff {result} is below minimum 0.1s"


class TestSingleSMTPCheck:
    """Test the single SMTP check function."""

    def test_single_smtp_check_timeout_handling(self) -> None:
        """_single_smtp_check should handle timeout gracefully."""
        import socket

        import app

        with patch("app.smtplib.SMTP") as mock_smtp:
            mock_instance = MagicMock()
            mock_smtp.return_value = mock_instance
            mock_instance.connect.side_effect = socket.timeout("Connection timed out")

            code, detail = app._single_smtp_check("test@example.com", "mx.example.com", 10)

            assert code is None
            assert detail == "timeout"

    def test_single_smtp_check_connection_refused(self) -> None:
        """_single_smtp_check should handle connection refused."""
        import app

        with patch("app.smtplib.SMTP") as mock_smtp:
            mock_instance = MagicMock()
            mock_smtp.return_value = mock_instance
            mock_instance.connect.side_effect = ConnectionRefusedError()

            code, detail = app._single_smtp_check("test@example.com", "mx.example.com", 10)

            assert code is None
            assert detail == "connection_refused"

    def test_single_smtp_check_success(self) -> None:
        """_single_smtp_check should return code on success."""
        import app

        with patch("app.smtplib.SMTP") as mock_smtp:
            mock_instance = MagicMock()
            mock_smtp.return_value = mock_instance
            mock_instance.rcpt.return_value = (250, b"OK")

            code, detail = app._single_smtp_check("test@example.com", "mx.example.com", 10)

            assert code == 250
            assert detail == "success"


class TestSMTPCheckWithRetry:
    """Test SMTP check with retry logic."""

    def test_retry_on_timeout(self) -> None:
        """Should retry on timeout."""
        import app

        call_count = 0

        def mock_single_check(email: str, mx: str, timeout: int) -> tuple[int | None, str]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None, "timeout"
            return 250, "success"

        with patch.object(app, "_single_smtp_check", side_effect=mock_single_check):
            with patch.object(app, "_jittered_backoff", return_value=0.01):
                code, reason = app._smtp_check_with_retry("test@example.com", "mx.example.com")

        # Should have retried
        assert call_count == 2, f"Expected 2 calls, got {call_count}"
        assert code == 250
        assert reason == "smtp_ok"

    def test_no_retry_on_hard_reject(self) -> None:
        """Should not retry on 5xx hard reject."""
        import app

        call_count = 0

        def mock_single_check(email: str, mx: str, timeout: int) -> tuple[int | None, str]:
            nonlocal call_count
            call_count += 1
            return 550, "reject"

        with patch.object(app, "_single_smtp_check", side_effect=mock_single_check):
            code, reason = app._smtp_check_with_retry("test@example.com", "mx.example.com")

        # Should NOT have retried
        assert call_count == 1, f"Expected 1 call, got {call_count}"
        assert code == 550
        assert reason == "smtp_reject_550"

    def test_retry_on_4xx_temp_fail(self) -> None:
        """Should retry on 4xx temporary failure."""
        import app

        call_count = 0

        def mock_single_check(email: str, mx: str, timeout: int) -> tuple[int | None, str]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return 450, "temp_fail"
            return 250, "success"

        with patch.object(app, "_single_smtp_check", side_effect=mock_single_check):
            with patch.object(app, "_jittered_backoff", return_value=0.01):
                code, reason = app._smtp_check_with_retry("test@example.com", "mx.example.com")

        # Should have retried
        assert call_count == 2
        assert code == 250
        assert reason == "smtp_ok"

    def test_returns_timeout_after_retry_when_all_fail(self) -> None:
        """Should return 'timeout_after_retry' when all retries fail with timeout."""
        import app
        from config import Config

        def mock_single_check(email: str, mx: str, timeout: int) -> tuple[int | None, str]:
            return None, "timeout"

        with patch.object(app, "_single_smtp_check", side_effect=mock_single_check):
            with patch.object(app, "_jittered_backoff", return_value=0.01):
                code, reason = app._smtp_check_with_retry("test@example.com", "mx.example.com")

        assert code is None
        # If SMTP_RETRIES > 0, should say "after_retry"
        if Config.SMTP_RETRIES > 0:
            assert reason == "timeout_after_retry"
        else:
            assert reason == "smtp_timeout"

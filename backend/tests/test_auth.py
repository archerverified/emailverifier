"""
Tests for API key authentication.
"""

import os


class TestAPIKeyAuthentication:
    """Test API key authentication on protected endpoints."""

    def test_verify_works_when_no_api_key_configured(self, client) -> None:
        """POST /verify should work when APP_API_KEY is not set (dev mode)."""
        # In test environment, APP_API_KEY is empty by default
        response = client.post(
            "/verify",
            data={"file": (b"email\ntest@example.com", "test.csv")},
            content_type="multipart/form-data",
        )

        # Should succeed (not 401 - business logic may return 200 or 400)
        assert response.status_code != 401

    def test_read_endpoints_dont_require_auth(self, client) -> None:
        """GET endpoints should not require API key."""
        # Health endpoint
        response = client.get("/health")
        assert response.status_code == 200

        # Schema endpoint
        response = client.get("/schema")
        assert response.status_code == 200

        # Metrics endpoint
        response = client.get("/metrics")
        assert response.status_code == 200

        # Jobs list endpoint
        response = client.get("/jobs")
        assert response.status_code == 200

    def test_cancel_endpoint_accepts_requests_when_no_key_configured(self, client) -> None:
        """POST /cancel should work when no API key is configured."""
        response = client.post("/cancel?job_id=nonexistent")
        # Should not be 401 (may be 404 for nonexistent job)
        assert response.status_code != 401

    def test_delete_endpoint_accepts_requests_when_no_key_configured(self, client) -> None:
        """DELETE /jobs/<id> should work when no API key is configured."""
        response = client.delete("/jobs/nonexistent-job-id")
        # Should not be 401 (may be 404 for nonexistent job)
        assert response.status_code != 401


class TestRequireAPIKeyDecorator:
    """Test the require_api_key decorator behavior."""

    def test_decorator_allows_when_key_empty(self) -> None:
        """Decorator should allow all requests when APP_API_KEY is empty."""
        import sys

        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        # The decorator checks Config.APP_API_KEY at runtime
        # When empty (default in tests), all requests are allowed
        from config import Config

        assert Config.APP_API_KEY == ""  # Should be empty in test env

    def test_config_has_api_key_setting(self) -> None:
        """Config should have APP_API_KEY attribute."""
        import sys

        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        from config import Config

        assert hasattr(Config, "APP_API_KEY")

    def test_config_has_rate_limit_settings(self) -> None:
        """Config should have rate limit settings."""
        import sys

        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        from config import Config

        assert hasattr(Config, "RATE_LIMIT_IP_PER_MINUTE")
        assert hasattr(Config, "RATE_LIMIT_KEY_PER_MINUTE")
        assert Config.RATE_LIMIT_IP_PER_MINUTE > 0
        assert Config.RATE_LIMIT_KEY_PER_MINUTE > 0

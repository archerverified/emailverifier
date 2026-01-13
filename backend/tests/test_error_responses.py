"""
Tests for structured error responses and version endpoints.
"""

import io
from unittest.mock import patch


class TestErrorEnvelopes:
    """Test structured error response format."""

    def test_429_error_has_structured_envelope(self, client):
        """Test that 429 response has structured error envelope."""
        with patch("app.get_running_jobs_count") as mock_count:
            # Force the concurrent job limit to be exceeded
            from config import Config

            mock_count.return_value = Config.MAX_CONCURRENT_JOBS

            csv_content = "name,email\nUser1,user1@example.com\n"
            data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}
            response = client.post("/verify", data=data, content_type="multipart/form-data")

            assert response.status_code == 429
            json_data = response.json

            # Check structured error envelope
            assert "error" in json_data
            assert isinstance(json_data["error"], dict)
            assert "code" in json_data["error"]
            assert "message" in json_data["error"]
            assert json_data["error"]["code"] == "TOO_MANY_CONCURRENT_JOBS"

            # Check request_id
            assert "request_id" in json_data

            # Check details
            assert "details" in json_data["error"]
            assert "running_jobs" in json_data["error"]["details"]
            assert "max_allowed" in json_data["error"]["details"]

    def test_400_no_email_column_has_structured_envelope(self, client):
        """Test that 400 error for missing email column has structured envelope."""
        csv_content = "name,company\nAlice,Acme\n"  # No email column
        data = {"file": (io.BytesIO(csv_content.encode()), "no_email.csv")}
        response = client.post("/verify", data=data, content_type="multipart/form-data")

        assert response.status_code == 400
        json_data = response.json

        # Check structured error envelope
        assert "error" in json_data
        assert isinstance(json_data["error"], dict)
        assert "code" in json_data["error"]
        assert "message" in json_data["error"]
        assert json_data["error"]["code"] == "NO_EMAIL_COLUMN"

        # Check request_id
        assert "request_id" in json_data

        # Check details
        assert "details" in json_data["error"]
        assert "available_columns" in json_data["error"]["details"]

    def test_400_column_not_found_has_structured_envelope(self, client):
        """Test that 400 error for column not found has structured envelope."""
        csv_content = "name,email\nAlice,alice@example.com\n"
        data = {
            "file": (io.BytesIO(csv_content.encode()), "test.csv"),
            "email_column": "nonexistent_column",
        }
        response = client.post("/verify", data=data, content_type="multipart/form-data")

        assert response.status_code == 400
        json_data = response.json

        # Check structured error envelope
        assert "error" in json_data
        assert isinstance(json_data["error"], dict)
        assert "code" in json_data["error"]
        assert json_data["error"]["code"] == "COLUMN_NOT_FOUND"
        assert "request_id" in json_data

    def test_400_multiple_email_columns_has_structured_envelope(self, client):
        """Test that 400 error for multiple email columns has structured envelope."""
        csv_content = "name,email,contact_email\nAlice,alice@a.com,alice@b.com\n"
        data = {"file": (io.BytesIO(csv_content.encode()), "multi_email.csv")}
        response = client.post("/verify", data=data, content_type="multipart/form-data")

        assert response.status_code == 400
        json_data = response.json

        # Check structured error envelope
        assert "error" in json_data
        assert isinstance(json_data["error"], dict)
        assert "code" in json_data["error"]
        assert json_data["error"]["code"] == "MULTIPLE_EMAIL_COLUMNS"
        assert "request_id" in json_data

        # Check details include candidates
        assert "details" in json_data["error"]
        assert "email_column_candidates" in json_data["error"]["details"]
        assert len(json_data["error"]["details"]["email_column_candidates"]) >= 2


class TestVersionEndpoints:
    """Test version information in API responses."""

    def test_schema_includes_server_version(self, client):
        """Test that /schema includes server_version."""
        response = client.get("/schema")
        assert response.status_code == 200
        json_data = response.json

        assert "server_version" in json_data
        assert json_data["server_version"] == "2.0.0"

        # Other fields should still be present
        assert "validator_mode" in json_data
        assert "scoring_version" in json_data
        assert "download_types" in json_data

    def test_metrics_includes_server_version(self, client):
        """Test that /metrics includes server_version."""
        response = client.get("/metrics")
        assert response.status_code == 200
        json_data = response.json

        assert "server_version" in json_data
        assert json_data["server_version"] == "2.0.0"

        # Other fields should still be present
        assert "status" in json_data
        assert json_data["status"] == "ok"
        assert "timestamp" in json_data
        assert "validator_mode" in json_data
        assert "jobs" in json_data
        assert "storage" in json_data

    def test_health_still_works(self, client):
        """Test that /health endpoint still works."""
        response = client.get("/health")
        assert response.status_code == 200
        json_data = response.json

        assert json_data == {"status": "ok"}


class TestRequestIdTracking:
    """Test request ID tracking in responses."""

    def test_response_includes_request_id_header(self, client):
        """Test that response includes X-Request-ID header."""
        response = client.get("/health")
        assert "X-Request-ID" in response.headers
        assert len(response.headers["X-Request-ID"]) > 0

    def test_provided_request_id_is_echoed(self, client):
        """Test that provided request ID is echoed back."""
        custom_id = "my-custom-request-id-12345"
        response = client.get("/health", headers={"X-Request-ID": custom_id})
        assert response.headers["X-Request-ID"] == custom_id

    def test_error_response_includes_request_id(self, client):
        """Test that error responses include request_id field."""
        csv_content = "name,company\nAlice,Acme\n"  # No email column
        data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}
        response = client.post(
            "/verify",
            data=data,
            content_type="multipart/form-data",
            headers={"X-Request-ID": "test-req-123"},
        )

        assert response.status_code == 400
        json_data = response.json
        assert json_data["request_id"] == "test-req-123"

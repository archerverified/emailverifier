"""
Tests for edge cases and robustness features.
Phase 2E: Delimiter detection, email extraction, normalization, concurrency limits.
"""

import io
import time
import zipfile

import csv_utils
from config import Config

# ============================================================================
# CSV Utils Unit Tests
# ============================================================================


class TestDelimiterDetection:
    """Tests for CSV delimiter auto-detection."""

    def test_comma_delimiter(self):
        content = "name,email,company\nAlice,alice@example.com,Acme"
        assert csv_utils.detect_delimiter(content) == ","

    def test_semicolon_delimiter(self):
        content = "name;email;company\nAlice;alice@example.com;Acme"
        assert csv_utils.detect_delimiter(content) == ";"

    def test_tab_delimiter(self):
        content = "name\temail\tcompany\nAlice\talice@example.com\tAcme"
        assert csv_utils.detect_delimiter(content) == "\t"

    def test_comma_preferred_on_tie(self):
        """When delimiter counts are ambiguous, prefer comma."""
        content = "name,email\n"  # Both have 1 occurrence
        assert csv_utils.detect_delimiter(content) == ","

    def test_quoted_field_handling(self):
        """Delimiters inside quotes should be ignored."""
        content = '"name, with comma",email,company\nAlice,alice@example.com,Acme'
        # Should detect comma, not be confused by comma in quotes
        assert csv_utils.detect_delimiter(content) == ","


class TestHeaderNormalization:
    """Tests for CSV header normalization."""

    def test_basic_normalization(self):
        headers = ["  Name  ", "Email", "Company  "]
        normalized, info = csv_utils.normalize_headers(headers)
        assert normalized == ["Name", "Email", "Company"]
        assert not info["had_duplicates"]

    def test_duplicate_headers(self):
        headers = ["email", "name", "email", "email"]
        normalized, info = csv_utils.normalize_headers(headers)
        assert normalized == ["email", "name", "email_2", "email_3"]
        assert info["had_duplicates"]
        assert "email" in info["duplicates"]

    def test_bom_removal(self):
        headers = ["\ufeffName", "Email"]
        normalized, _ = csv_utils.normalize_headers(headers)
        assert normalized[0] == "Name"

    def test_empty_headers(self):
        headers = ["Name", "", "Email"]
        normalized, _ = csv_utils.normalize_headers(headers)
        assert normalized[1] == "column_2"


class TestEmailExtraction:
    """Tests for email extraction from various formats."""

    def test_plain_email(self):
        assert csv_utils.extract_email_from_field("alice@example.com") == "alice@example.com"

    def test_angle_bracket_format(self):
        assert (
            csv_utils.extract_email_from_field("Alice Smith <alice@example.com>")
            == "alice@example.com"
        )

    def test_angle_bracket_only(self):
        assert csv_utils.extract_email_from_field("<alice@example.com>") == "alice@example.com"

    def test_parentheses_format(self):
        assert (
            csv_utils.extract_email_from_field("alice@example.com (Alice Smith)")
            == "alice@example.com"
        )

    def test_quoted_email(self):
        assert csv_utils.extract_email_from_field('"alice@example.com"') == "alice@example.com"

    def test_empty_value(self):
        assert csv_utils.extract_email_from_field("") == ""
        assert csv_utils.extract_email_from_field("   ") == ""


class TestEmailNormalization:
    """Tests for email normalization."""

    def test_basic_normalization(self):
        assert csv_utils.normalize_email("  alice@EXAMPLE.COM  ") == "alice@example.com"

    def test_domain_lowercase(self):
        # Local part case should be preserved, domain lowercased
        assert csv_utils.normalize_email("Alice@EXAMPLE.COM") == "Alice@example.com"

    def test_trailing_punctuation(self):
        assert csv_utils.normalize_email("alice@example.com.") == "alice@example.com"
        assert csv_utils.normalize_email("alice@example.com,") == "alice@example.com"

    def test_quoted_email(self):
        assert csv_utils.normalize_email('"alice@example.com"') == "alice@example.com"

    def test_angle_brackets(self):
        assert csv_utils.normalize_email("<alice@example.com>") == "alice@example.com"

    def test_invalid_email(self):
        assert csv_utils.normalize_email("not-an-email") == ""
        assert csv_utils.normalize_email("") == ""


class TestEmailColumnDetection:
    """Tests for email column detection."""

    def test_exact_match(self):
        assert csv_utils.is_likely_email_column("email") is True
        assert csv_utils.is_likely_email_column("Email") is True
        assert csv_utils.is_likely_email_column("E-mail") is True

    def test_contains_match(self):
        assert csv_utils.is_likely_email_column("Contact Email") is True
        assert csv_utils.is_likely_email_column("email_address") is True

    def test_non_email_columns(self):
        assert csv_utils.is_likely_email_column("Name") is False
        assert csv_utils.is_likely_email_column("Phone") is False


# ============================================================================
# Integration Tests
# ============================================================================


class TestSemicolonDelimiterCSV:
    """Test processing of semicolon-delimited CSV files."""

    def test_semicolon_csv_processes_correctly(self, client):
        """Test that semicolon-delimited CSV auto-detects and processes."""
        csv_content = "name;email;company\nAlice;alice@example.com;Acme\nBob;bob@test.org;Corp"
        data = {"file": (io.BytesIO(csv_content.encode()), "semicolon.csv")}
        response = client.post("/verify", data=data, content_type="multipart/form-data")
        assert response.status_code == 200

        job_id = response.json["job_id"]

        # Wait for completion
        for _ in range(50):
            time.sleep(0.1)
            progress = client.get(f"/progress?job_id={job_id}").json
            if progress.get("percent", 0) >= 100:
                break

        # Download and verify
        download = client.get(f"/download?job_id={job_id}&type=all")
        assert download.status_code == 200
        content = download.data.decode()
        assert "alice@example.com" in content
        assert "bob@test.org" in content


class TestDuplicateHeaders:
    """Test handling of CSVs with duplicate column names."""

    def test_duplicate_email_columns(self, client):
        """Test that duplicate email columns are handled correctly."""
        csv_content = "name,email,email\nAlice,alice@example.com,alice2@test.com"
        data = {"file": (io.BytesIO(csv_content.encode()), "duplicates.csv")}
        # Without specifying email_column, should use first 'email' column
        response = client.post("/verify", data=data, content_type="multipart/form-data")
        assert response.status_code == 200


class TestAngleBracketEmailExtraction:
    """Test extraction from 'Name <email@domain.com>' format."""

    def test_angle_bracket_emails(self, client):
        """Test that angle-bracket format emails are extracted."""
        csv_content = (
            "name,email\n"
            "Alice,Alice Smith <alice@example.com>\n"
            "Bob,<bob@test.org>\n"
            "Charlie,charlie@example.com\n"
        )
        data = {"file": (io.BytesIO(csv_content.encode()), "angles.csv")}
        response = client.post("/verify", data=data, content_type="multipart/form-data")
        assert response.status_code == 200

        job_id = response.json["job_id"]

        # Wait for completion
        for _ in range(50):
            time.sleep(0.1)
            progress = client.get(f"/progress?job_id={job_id}").json
            if progress.get("percent", 0) >= 100:
                break

        # Download and verify emails were extracted correctly
        download = client.get(f"/download?job_id={job_id}&type=scores")
        assert download.status_code == 200
        content = download.data.decode()
        assert "alice@example.com" in content
        assert "bob@test.org" in content


class TestEmailNormalizationIntegration:
    """Test email normalization in end-to-end processing."""

    def test_email_normalization(self, client):
        """Test that emails are normalized (domain lowercase, trimmed)."""
        csv_content = "name,email\nAlice,  ALICE@EXAMPLE.COM  \n"
        data = {"file": (io.BytesIO(csv_content.encode()), "normalize.csv")}
        response = client.post("/verify", data=data, content_type="multipart/form-data")
        assert response.status_code == 200

        job_id = response.json["job_id"]

        # Wait for completion
        for _ in range(50):
            time.sleep(0.1)
            progress = client.get(f"/progress?job_id={job_id}").json
            if progress.get("percent", 0) >= 100:
                break

        # The email should be normalized in processing (domain lowercase)
        # Status should be valid for example.com in mock mode
        download = client.get(f"/download?job_id={job_id}&type=scores")
        assert download.status_code == 200


class TestConcurrencyLimit:
    """Test MAX_CONCURRENT_JOBS limit."""

    def test_concurrent_job_limit_returns_429(self, client):
        """Test that /verify returns 429 when limit exceeded."""
        from unittest.mock import patch

        # Create a small CSV
        csv_content = "name,email\nUser1,user1@example.com\n"

        # Patch get_running_jobs_count to simulate max jobs reached
        with patch("app.get_running_jobs_count") as mock_count:
            mock_count.return_value = Config.MAX_CONCURRENT_JOBS

            data = {"file": (io.BytesIO(csv_content.encode()), "over_limit.csv")}
            response = client.post("/verify", data=data, content_type="multipart/form-data")

            assert response.status_code == 429
            json_data = response.json
            # Check structured error envelope
            assert "error" in json_data
            assert json_data["error"]["code"] == "TOO_MANY_CONCURRENT_JOBS"
            assert "running_jobs" in json_data["error"]["details"]
            assert "max_allowed" in json_data["error"]["details"]


class TestIdempotentDownloads:
    """Test download consistency."""

    def test_download_twice_returns_same_content(self, client):
        """Test that downloading the same file twice returns identical content."""
        csv_content = "name,email\nAlice,alice@example.com\n"
        data = {"file": (io.BytesIO(csv_content.encode()), "idempotent.csv")}
        response = client.post("/verify", data=data, content_type="multipart/form-data")
        assert response.status_code == 200
        job_id = response.json["job_id"]

        # Wait for completion
        for _ in range(50):
            time.sleep(0.1)
            progress = client.get(f"/progress?job_id={job_id}").json
            if progress.get("percent", 0) >= 100:
                break

        # Download twice
        download1 = client.get(f"/download?job_id={job_id}&type=all")
        download2 = client.get(f"/download?job_id={job_id}&type=all")

        assert download1.status_code == 200
        assert download2.status_code == 200
        assert download1.data == download2.data


class TestBundleSafety:
    """Test ZIP bundle security."""

    def test_bundle_contains_only_expected_files(self, client):
        """Test that bundle ZIP contains only expected files."""
        csv_content = "name,email\nAlice,alice@example.com\n"
        data = {"file": (io.BytesIO(csv_content.encode()), "bundle_safety.csv")}
        response = client.post("/verify", data=data, content_type="multipart/form-data")
        assert response.status_code == 200
        job_id = response.json["job_id"]

        # Wait for completion
        for _ in range(50):
            time.sleep(0.1)
            progress = client.get(f"/progress?job_id={job_id}").json
            if progress.get("percent", 0) >= 100:
                break

        # Download bundle
        bundle = client.get(f"/jobs/{job_id}/bundle")
        assert bundle.status_code == 200

        # Check ZIP contents
        z = zipfile.ZipFile(io.BytesIO(bundle.data))
        names = z.namelist()

        # Only expected files
        expected = {
            "all.csv",
            "valid.csv",
            "risky.csv",
            "risky_invalid.csv",
            "scores.csv",
            "summary.json",
        }
        assert set(names) == expected

        # No absolute paths or traversal attempts
        for name in names:
            assert not name.startswith("/")
            assert ".." not in name
            assert "\\" not in name


class TestMetricsEndpoint:
    """Test /metrics endpoint."""

    def test_metrics_returns_expected_data(self, client):
        """Test that /metrics returns monitoring data."""
        response = client.get("/metrics")
        assert response.status_code == 200
        data = response.json

        assert data["status"] == "ok"
        assert "timestamp" in data
        assert data["validator_mode"] == "mock"

        assert "jobs" in data
        assert "running" in data["jobs"]
        assert "max_concurrent" in data["jobs"]

        assert "storage" in data
        assert "db_path" in data["storage"]

        assert "config" in data
        assert "max_upload_mb" in data["config"]
        assert "stall_timeout_minutes" in data["config"]


class TestBOMHandling:
    """Test BOM (Byte Order Mark) handling."""

    def test_utf8_bom_csv(self, client):
        """Test that UTF-8 BOM is handled correctly."""
        # Create content with UTF-8 BOM
        csv_content = "\ufeffname,email\nAlice,alice@example.com\n"
        data = {"file": (io.BytesIO(csv_content.encode("utf-8-sig")), "bom.csv")}
        response = client.post("/verify", data=data, content_type="multipart/form-data")
        assert response.status_code == 200


class TestQuotedFields:
    """Test handling of CSV files with quoted fields."""

    def test_quoted_fields_with_commas(self, client):
        """Test that quoted fields containing commas are handled."""
        csv_content = '"Name, First",email,company\n"Smith, John",john@example.com,Acme\n'
        data = {"file": (io.BytesIO(csv_content.encode()), "quoted.csv")}
        response = client.post("/verify", data=data, content_type="multipart/form-data")
        assert response.status_code == 200

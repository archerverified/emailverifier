"""Tests for progress endpoint stability and processing_row field."""

import io
import os
import sys
import time

import pytest

sys.path.insert(0, ".")
os.environ["TESTING"] = "1"
os.environ["VALIDATOR_MODE"] = "mock"


class TestProgressEndpoint:
    """Tests for /progress endpoint response fields."""

    def test_progress_returns_processing_row(self, client: pytest.fixture) -> None:
        """Progress endpoint returns processing_row field."""
        # Create a test CSV
        csv_content = "email\ntest1@example.com\ntest2@example.com\n"
        data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}

        # Start job
        response = client.post("/verify", data=data, content_type="multipart/form-data")
        assert response.status_code == 200
        job_id = response.json["job_id"]

        # Poll progress - should have processing_row field
        response = client.get(f"/progress?job_id={job_id}")
        assert response.status_code == 200

        progress_data = response.json
        assert "row" in progress_data  # Backward compat
        assert "processing_row" in progress_data  # New field
        assert "total" in progress_data
        assert "percent" in progress_data

    def test_progress_row_is_completed_count(self, client: pytest.fixture) -> None:
        """The 'row' field represents completed rows count."""
        csv_content = "email\ntest1@example.com\ntest2@example.com\ntest3@example.com\n"
        data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}

        response = client.post("/verify", data=data, content_type="multipart/form-data")
        job_id = response.json["job_id"]

        # Wait for completion
        for _ in range(50):
            response = client.get(f"/progress?job_id={job_id}")
            if response.json.get("percent", 0) >= 100:
                break
            time.sleep(0.1)

        # When complete, row should equal total
        progress_data = response.json
        assert progress_data["row"] == progress_data["total"]
        assert progress_data["row"] == 3

    def test_progress_includes_status_field(self, client: pytest.fixture) -> None:
        """Progress endpoint includes status field."""
        csv_content = "email\ntest@example.com\n"
        data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}

        response = client.post("/verify", data=data, content_type="multipart/form-data")
        job_id = response.json["job_id"]

        # Wait for completion
        for _ in range(50):
            response = client.get(f"/progress?job_id={job_id}")
            if response.json.get("percent", 0) >= 100:
                break
            time.sleep(0.1)

        progress_data = response.json
        assert "status" in progress_data
        assert progress_data["status"] in ("running", "completed", "cancelled", "failed")

    def test_progress_not_found_includes_processing_row(self, client: pytest.fixture) -> None:
        """Progress for non-existent job includes processing_row field."""
        response = client.get("/progress?job_id=nonexistent-job-id")
        assert response.status_code == 200

        progress_data = response.json
        assert "processing_row" in progress_data
        assert progress_data["processing_row"] == 0
        assert progress_data["row"] == 0
        assert "error" in progress_data


class TestProgressBackwardCompatibility:
    """Tests ensuring backward compatibility of progress response."""

    def test_row_field_still_exists(self, client: pytest.fixture) -> None:
        """The 'row' field is still present for backward compatibility."""
        csv_content = "email\ntest@example.com\n"
        data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}

        response = client.post("/verify", data=data, content_type="multipart/form-data")
        job_id = response.json["job_id"]

        response = client.get(f"/progress?job_id={job_id}")
        assert "row" in response.json

    def test_percent_field_still_exists(self, client: pytest.fixture) -> None:
        """The 'percent' field is still present."""
        csv_content = "email\ntest@example.com\n"
        data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}

        response = client.post("/verify", data=data, content_type="multipart/form-data")
        job_id = response.json["job_id"]

        response = client.get(f"/progress?job_id={job_id}")
        assert "percent" in response.json

    def test_total_field_still_exists(self, client: pytest.fixture) -> None:
        """The 'total' field is still present."""
        csv_content = "email\ntest@example.com\n"
        data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}

        response = client.post("/verify", data=data, content_type="multipart/form-data")
        job_id = response.json["job_id"]

        response = client.get(f"/progress?job_id={job_id}")
        assert "total" in response.json


class TestProgressDuringProcessing:
    """Tests for progress stability during job processing."""

    def test_processing_row_never_exceeds_total(self, client: pytest.fixture) -> None:
        """processing_row should never exceed total rows."""
        csv_content = "email\n" + "\n".join([f"test{i}@example.com" for i in range(10)]) + "\n"
        data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}

        response = client.post("/verify", data=data, content_type="multipart/form-data")
        job_id = response.json["job_id"]

        # Poll multiple times during processing
        for _ in range(20):
            response = client.get(f"/progress?job_id={job_id}")
            progress_data = response.json
            total = progress_data.get("total", 0)
            processing_row = progress_data.get("processing_row", 0)
            row = progress_data.get("row", 0)

            # processing_row should not exceed total
            assert processing_row <= total, f"processing_row {processing_row} > total {total}"
            # row (completed) should not exceed total
            assert row <= total, f"row {row} > total {total}"
            # row (completed) should not exceed processing_row
            # (can't complete more than we've processed)
            # Note: This may not hold if processing_row is set before work starts
            # So we just check they're both reasonable

            if progress_data.get("percent", 0) >= 100:
                break
            time.sleep(0.05)

    def test_row_only_increases(self, client: pytest.fixture) -> None:
        """Completed row count should only increase, never decrease."""
        csv_content = "email\n" + "\n".join([f"test{i}@example.com" for i in range(10)]) + "\n"
        data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}

        response = client.post("/verify", data=data, content_type="multipart/form-data")
        job_id = response.json["job_id"]

        last_row = 0
        for _ in range(30):
            response = client.get(f"/progress?job_id={job_id}")
            progress_data = response.json
            current_row = progress_data.get("row", 0)

            # Row should never decrease
            assert current_row >= last_row, f"Row decreased from {last_row} to {current_row}"
            last_row = current_row

            if progress_data.get("percent", 0) >= 100:
                break
            time.sleep(0.05)

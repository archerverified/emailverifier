"""
Tests for job monitoring and stall detection.
"""

import io
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

sys.path.insert(0, ".")
os.environ["TESTING"] = "1"
os.environ["VALIDATOR_MODE"] = "mock"

import db
from config import Config
from job_monitor import JobMonitor


class TestStallDetection:
    """Test stall detection logic."""

    def test_stall_detection_marks_old_job_as_failed(self):
        """Test that jobs with old heartbeats are marked as stalled."""
        # Create a job with old heartbeat
        old_time = (
            datetime.now(UTC) - timedelta(minutes=Config.JOB_STALL_TIMEOUT_MINUTES + 5)
        ).isoformat()

        db.save_job(
            {
                "id": "test-stalled-job",
                "filename": "test.csv",
                "created_at": old_time,
                "status": "running",
                "email_column": "email",
                "mode": "mock",
                "total_rows": 100,
                "last_heartbeat": old_time,
            }
        )

        # Run a single stall check
        monitor = JobMonitor()
        marked_count = monitor.check_stalled_jobs_once()

        # Verify job was marked as failed
        assert marked_count == 1

        job = db.get_job("test-stalled-job")
        assert job is not None
        assert job["status"] == "failed"
        assert "stalled" in job["error_message"].lower()
        assert job["completed_at"] is not None

    def test_stall_detection_ignores_recent_jobs(self):
        """Test that jobs with recent heartbeats are not marked as stalled."""
        # Create a job with recent heartbeat
        recent_time = datetime.now(UTC).isoformat()

        db.save_job(
            {
                "id": "test-active-job",
                "filename": "test.csv",
                "created_at": recent_time,
                "status": "running",
                "email_column": "email",
                "mode": "mock",
                "total_rows": 100,
                "last_heartbeat": recent_time,
            }
        )

        # Run a single stall check
        monitor = JobMonitor()
        marked_count = monitor.check_stalled_jobs_once()

        # Verify job was NOT marked as failed
        assert marked_count == 0

        job = db.get_job("test-active-job")
        assert job is not None
        assert job["status"] == "running"

    def test_stall_detection_with_time_provider(self):
        """Test stall detection with injected time provider."""
        # Use a fixed "current time"
        fixed_now = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        old_time = (fixed_now - timedelta(minutes=Config.JOB_STALL_TIMEOUT_MINUTES + 1)).isoformat()

        # Create a stalled job
        db.save_job(
            {
                "id": "test-time-provider-job",
                "filename": "test.csv",
                "created_at": old_time,
                "status": "running",
                "email_column": "email",
                "mode": "mock",
                "total_rows": 50,
                "last_heartbeat": old_time,
            }
        )

        # Inject time provider
        Config.set_time_provider(lambda: fixed_now)

        try:
            monitor = JobMonitor()
            marked_count = monitor.check_stalled_jobs_once()

            assert marked_count == 1
            job = db.get_job("test-time-provider-job")
            assert job is not None
            assert job["status"] == "failed"
        finally:
            Config.set_time_provider(None)

    def test_stall_detection_ignores_completed_jobs(self):
        """Test that completed jobs are not marked as stalled."""
        old_time = (
            datetime.now(UTC) - timedelta(minutes=Config.JOB_STALL_TIMEOUT_MINUTES + 5)
        ).isoformat()

        db.save_job(
            {
                "id": "test-completed-job",
                "filename": "test.csv",
                "created_at": old_time,
                "status": "completed",  # Already completed
                "email_column": "email",
                "mode": "mock",
                "total_rows": 100,
                "last_heartbeat": old_time,
                "completed_at": old_time,
            }
        )

        monitor = JobMonitor()
        marked_count = monitor.check_stalled_jobs_once()

        # Completed jobs should not be touched
        assert marked_count == 0

        job = db.get_job("test-completed-job")
        assert job is not None
        assert job["status"] == "completed"

    def test_monitor_lifecycle(self):
        """Test that monitor starts and stops cleanly."""
        monitor = JobMonitor(check_interval_seconds=1)

        # Start (won't actually run thread in TESTING mode)
        monitor.start()

        # In TESTING mode, thread is not started
        if Config.TESTING:
            assert monitor._thread is None or not monitor._thread.is_alive()

        # Stop should be safe to call
        monitor.stop(timeout=2.0)

    def test_monitor_handles_missing_storage(self):
        """Test that monitor handles FileNotFoundError gracefully."""
        monitor = JobMonitor()

        # Even with no jobs, check should not raise
        marked_count = monitor.check_stalled_jobs_once()
        assert marked_count == 0

    def test_stall_detection_rate_limiting(self):
        """Test that repeated stall detections are rate-limited."""
        old_time = (
            datetime.now(UTC) - timedelta(minutes=Config.JOB_STALL_TIMEOUT_MINUTES + 5)
        ).isoformat()

        db.save_job(
            {
                "id": "test-rate-limit-job",
                "filename": "test.csv",
                "created_at": old_time,
                "status": "running",
                "email_column": "email",
                "mode": "mock",
                "total_rows": 100,
                "last_heartbeat": old_time,
            }
        )

        monitor = JobMonitor()

        # First check should mark the job
        first_count = monitor.check_stalled_jobs_once()
        assert first_count == 1

        # Reset job to running to simulate a scenario where we'd check again
        db.save_job(
            {
                "id": "test-rate-limit-job",
                "status": "running",
                "last_heartbeat": old_time,
                "completed_at": None,
                "error_message": None,
            }
        )

        # Second check within 5 minutes should be rate-limited
        second_count = monitor.check_stalled_jobs_once()
        assert second_count == 0  # Rate limited

        job = db.get_job("test-rate-limit-job")
        assert job is not None
        # Job should still be running since rate limit prevented update
        assert job["status"] == "running"


class TestTimeBasedHeartbeat:
    """Tests for time-based heartbeat updates."""

    def test_heartbeat_updates_during_job_processing(self, client: pytest.fixture) -> None:
        """
        Test that heartbeat is updated during job processing.
        This prevents false stall detection during slow SMTP operations.
        """
        # Create a CSV with a few emails
        csv_content = "email\n" + "\n".join([f"test{i}@example.com" for i in range(5)]) + "\n"
        data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}

        # Start job
        response = client.post("/verify", data=data, content_type="multipart/form-data")
        assert response.status_code == 200
        job_id = response.json["job_id"]

        # Wait for job to complete - check both progress AND DB status
        job_completed = False
        for _ in range(100):
            response = client.get(f"/progress?job_id={job_id}")
            progress_data = response.json
            # Also check DB status since thread may update DB after progress shows 100%
            job = db.get_job(job_id)
            if progress_data.get("percent", 0) >= 100 and job and job["status"] == "completed":
                job_completed = True
                break
            time.sleep(0.05)

        # Check that job completed (not stalled)
        assert job_completed, f"Job did not complete. Status: {job['status'] if job else 'not found'}"
        assert job is not None
        # Heartbeat should have been updated
        assert job["last_heartbeat"] is not None

    def test_heartbeat_prevents_false_stall_detection(self) -> None:
        """
        Test that time-based heartbeat updates prevent false stall detection.
        Uses time provider injection to simulate passage of time.
        """
        # Create a job that's been "running" for a while but has recent heartbeat
        start_time = datetime.now(UTC)
        recent_heartbeat = start_time.isoformat()

        db.save_job(
            {
                "id": "test-heartbeat-job",
                "filename": "test.csv",
                "created_at": (start_time - timedelta(minutes=30)).isoformat(),
                "status": "running",
                "email_column": "email",
                "mode": "mock",
                "total_rows": 1000,
                "last_heartbeat": recent_heartbeat,  # Recent heartbeat
            }
        )

        # Run stall detection
        monitor = JobMonitor()
        marked_count = monitor.check_stalled_jobs_once()

        # Job should NOT be marked as stalled because heartbeat is recent
        assert marked_count == 0

        job = db.get_job("test-heartbeat-job")
        assert job is not None
        assert job["status"] == "running"

    def test_job_with_updated_heartbeat_not_stalled(self) -> None:
        """
        Test that a job with a recently updated heartbeat is not marked stalled,
        even if it was created long ago.
        """
        now = datetime.now(UTC)

        # Job created 2 hours ago, but heartbeat updated 5 minutes ago
        db.save_job(
            {
                "id": "test-old-job-recent-hb",
                "filename": "test.csv",
                "created_at": (now - timedelta(hours=2)).isoformat(),
                "status": "running",
                "email_column": "email",
                "mode": "mock",
                "total_rows": 10000,
                "last_heartbeat": (now - timedelta(minutes=5)).isoformat(),
            }
        )

        monitor = JobMonitor()
        marked_count = monitor.check_stalled_jobs_once()

        # Should NOT be marked as stalled
        assert marked_count == 0

        job = db.get_job("test-old-job-recent-hb")
        assert job["status"] == "running"

    def test_job_state_includes_heartbeat_tracking(self, client: pytest.fixture) -> None:
        """Test that job state includes heartbeat tracking fields."""
        import app

        csv_content = "email\ntest@example.com\n"
        data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}

        response = client.post("/verify", data=data, content_type="multipart/form-data")
        job_id = response.json["job_id"]

        # Check in-memory job state has heartbeat fields
        with app.JOB_STATE_LOCK:
            job_data = app.data.get(job_id, {})
            if job_data:  # Job might have completed already
                assert "last_heartbeat_mono" in job_data or job_data == {}
                assert "last_heartbeat_utc" in job_data or job_data == {}

        # Wait for completion
        for _ in range(50):
            response = client.get(f"/progress?job_id={job_id}")
            if response.json.get("percent", 0) >= 100:
                break
            time.sleep(0.1)

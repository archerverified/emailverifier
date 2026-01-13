"""
Tests for job monitoring and stall detection.
"""

from datetime import UTC, datetime, timedelta

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

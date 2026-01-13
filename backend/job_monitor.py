"""
Job health monitoring with clean lifecycle management.
Detects and marks stalled jobs based on heartbeat timestamps.
"""

import logging
import threading
import time

import db
from config import Config

logger = logging.getLogger(__name__)


class JobMonitor:
    """
    Background job health monitor with controlled lifecycle.

    Features:
    - Checks for stalled jobs periodically
    - Clean shutdown via threading.Event
    - Resilient to file/DB access errors
    - Disabled in TESTING mode
    """

    def __init__(self, check_interval_seconds: int = 60):
        self.check_interval = check_interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_warning_time: dict[str, float] = {}  # Rate-limit warnings per job_id

    def start(self) -> None:
        """Start the monitoring thread."""
        if Config.TESTING:
            logger.debug("JobMonitor disabled in TESTING mode")
            return

        if self._thread and self._thread.is_alive():
            logger.warning("JobMonitor already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="JobMonitor")
        self._thread.start()
        logger.info("JobMonitor started")

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the monitoring thread and wait for it to finish."""
        if not self._thread:
            return

        self._stop_event.set()
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            logger.warning("JobMonitor did not stop within timeout")
        else:
            logger.debug("JobMonitor stopped")

    def check_stalled_jobs_once(self) -> int:
        """
        Run a single stall check iteration (for testing).
        Returns number of jobs marked as stalled.
        """
        try:
            stalled = db.get_stalled_jobs(Config.JOB_STALL_TIMEOUT_MINUTES)
            count = 0
            for job in stalled:
                # Rate-limit warnings (don't spam logs for same job)
                job_id = job["id"]
                now = time.time()
                if job_id in self._last_warning_time:
                    if now - self._last_warning_time[job_id] < 300:  # 5 minutes
                        continue

                db.save_job(
                    {
                        "id": job_id,
                        "status": "failed",
                        "error_message": (
                            f"Job stalled (no activity for "
                            f"{Config.JOB_STALL_TIMEOUT_MINUTES} minutes)"
                        ),
                        "completed_at": Config.now_utc().isoformat(),
                    }
                )
                logger.warning("Marked job as stalled", extra={"job_id": job_id})
                self._last_warning_time[job_id] = now
                count += 1
            return count
        except FileNotFoundError:
            # Storage dir removed during shutdown - ignore silently
            return 0
        except Exception as e:
            # Only log if not during shutdown
            if not self._stop_event.is_set():
                logger.error(f"Error checking stalled jobs: {e}")
            return 0

    def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while not self._stop_event.is_set():
            try:
                self.check_stalled_jobs_once()
            except Exception as e:
                if not self._stop_event.is_set():
                    logger.error(f"Unexpected error in JobMonitor: {e}")

            # Sleep in small intervals to allow quick shutdown
            for _ in range(self.check_interval):
                if self._stop_event.is_set():
                    break
                time.sleep(1)


# Global monitor instance
_monitor = JobMonitor()


def start_monitor() -> None:
    """Start the global job monitor."""
    _monitor.start()


def stop_monitor() -> None:
    """Stop the global job monitor."""
    _monitor.stop()


def get_monitor() -> JobMonitor:
    """Get the global monitor instance (for testing)."""
    return _monitor

"""
Redis-based job state management for horizontal scaling.

This module provides a centralized job state store using Redis,
enabling multiple Gunicorn workers to share job state consistently.

For testing, set REDIS_URL="" to use in-memory fallback.
"""

import json
import os
import threading
import time
from datetime import UTC, datetime
from typing import Any

# Try to import redis, fall back to in-memory for testing
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None  # type: ignore

from config import Config


class JobStateManager:
    """
    Manages job state in Redis for multi-worker deployments.
    
    Falls back to in-memory dict when Redis is not available (testing).
    """
    
    # Redis key prefixes
    KEY_PREFIX = "leadvalidator:"
    JOB_KEY = KEY_PREFIX + "job:"
    JOBS_SET = KEY_PREFIX + "active_jobs"
    
    # TTL for job data in Redis (24 hours)
    JOB_TTL_SECONDS = 86400
    
    def __init__(self, redis_url: str | None = None):
        """
        Initialize job state manager.
        
        Args:
            redis_url: Redis connection URL. If None, reads from REDIS_URL env var.
                      If empty string, uses in-memory fallback.
        """
        self._redis_url = redis_url if redis_url is not None else os.getenv("REDIS_URL", "")
        self._redis: Any = None
        self._memory_store: dict[str, dict] = {}
        self._memory_lock = threading.RLock()
        self._use_redis = False
        
        self._connect()
    
    def _connect(self) -> None:
        """Establish Redis connection or fall back to memory."""
        if not self._redis_url or not REDIS_AVAILABLE:
            self._use_redis = False
            return
        
        try:
            self._redis = redis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            # Test connection
            self._redis.ping()
            self._use_redis = True
        except Exception as e:
            print(f"WARNING: Redis connection failed ({e}), using in-memory fallback")
            self._use_redis = False
            self._redis = None
    
    def _job_key(self, job_id: str) -> str:
        """Get Redis key for a job."""
        return f"{self.JOB_KEY}{job_id}"
    
    def create_job(self, job_id: str, job_data: dict) -> None:
        """
        Create a new job in the state store.
        
        Args:
            job_id: Unique job identifier
            job_data: Initial job state dict
        """
        # Add timestamps
        now = time.time()
        job_data["created_at_mono"] = now
        job_data["last_heartbeat_mono"] = now
        job_data["last_heartbeat_utc"] = datetime.now(UTC).isoformat()
        
        if self._use_redis:
            # Store as JSON in Redis
            serializable = self._make_serializable(job_data)
            self._redis.hset(self._job_key(job_id), mapping={"data": json.dumps(serializable)})
            self._redis.expire(self._job_key(job_id), self.JOB_TTL_SECONDS)
            self._redis.sadd(self.JOBS_SET, job_id)
        else:
            with self._memory_lock:
                self._memory_store[job_id] = job_data.copy()
    
    def get_job(self, job_id: str) -> dict | None:
        """
        Get job state by ID.
        
        Args:
            job_id: Job identifier
            
        Returns:
            Job state dict or None if not found
        """
        if self._use_redis:
            data = self._redis.hget(self._job_key(job_id), "data")
            if data:
                return json.loads(data)
            return None
        else:
            with self._memory_lock:
                job = self._memory_store.get(job_id)
                return job.copy() if job else None
    
    def update_job(self, job_id: str, updates: dict) -> bool:
        """
        Update job state fields.
        
        Args:
            job_id: Job identifier
            updates: Dict of fields to update
            
        Returns:
            True if job exists and was updated, False otherwise
        """
        if self._use_redis:
            key = self._job_key(job_id)
            data = self._redis.hget(key, "data")
            if not data:
                return False
            
            job = json.loads(data)
            job.update(self._make_serializable(updates))
            self._redis.hset(key, mapping={"data": json.dumps(job)})
            self._redis.expire(key, self.JOB_TTL_SECONDS)
            return True
        else:
            with self._memory_lock:
                if job_id not in self._memory_store:
                    return False
                self._memory_store[job_id].update(updates)
                return True
    
    def update_progress(
        self,
        job_id: str,
        row: int,
        processing_row: int,
        percent: int,
        log: str,
    ) -> bool:
        """
        Update job progress (optimized for frequent updates).
        
        Args:
            job_id: Job identifier
            row: Completed row count
            processing_row: Currently processing row
            percent: Completion percentage
            log: Latest log message
            
        Returns:
            True if updated, False if job not found
        """
        updates = {
            "row": row,
            "processing_row": processing_row,
            "progress": percent,
            "log": log,
            "last_heartbeat_mono": time.time(),
            "last_heartbeat_utc": datetime.now(UTC).isoformat(),
        }
        return self.update_job(job_id, updates)
    
    def set_cancel(self, job_id: str) -> bool:
        """
        Mark a job for cancellation.
        
        Args:
            job_id: Job identifier
            
        Returns:
            True if job exists and was marked, False otherwise
        """
        return self.update_job(job_id, {"cancel": True})
    
    def is_cancelled(self, job_id: str) -> bool:
        """
        Check if a job is marked for cancellation.
        
        Args:
            job_id: Job identifier
            
        Returns:
            True if job is cancelled, False otherwise
        """
        job = self.get_job(job_id)
        return bool(job and job.get("cancel", False))
    
    def delete_job(self, job_id: str) -> bool:
        """
        Remove a job from the state store.
        
        Args:
            job_id: Job identifier
            
        Returns:
            True if job existed and was deleted, False otherwise
        """
        if self._use_redis:
            key = self._job_key(job_id)
            existed = self._redis.exists(key)
            self._redis.delete(key)
            self._redis.srem(self.JOBS_SET, job_id)
            return bool(existed)
        else:
            with self._memory_lock:
                if job_id in self._memory_store:
                    del self._memory_store[job_id]
                    return True
                return False
    
    def get_active_job_ids(self) -> list[str]:
        """
        Get list of all active job IDs.
        
        Returns:
            List of job IDs
        """
        if self._use_redis:
            return list(self._redis.smembers(self.JOBS_SET))
        else:
            with self._memory_lock:
                return list(self._memory_store.keys())
    
    def count_running_jobs(self) -> int:
        """
        Count jobs that are currently running (not completed/cancelled).
        
        Returns:
            Number of running jobs
        """
        count = 0
        for job_id in self.get_active_job_ids():
            job = self.get_job(job_id)
            if job and job.get("progress", 0) < 100 and not job.get("cancel"):
                count += 1
        return count
    
    def clear_all(self) -> None:
        """Clear all job state (for testing)."""
        if self._use_redis:
            for job_id in self.get_active_job_ids():
                self._redis.delete(self._job_key(job_id))
            self._redis.delete(self.JOBS_SET)
        else:
            with self._memory_lock:
                self._memory_store.clear()
    
    def _make_serializable(self, data: dict) -> dict:
        """
        Convert job data to JSON-serializable format.
        
        Removes non-serializable objects (file handles, writers, etc.)
        """
        result = {}
        for key, value in data.items():
            # Skip non-serializable objects
            if key in ("output", "writer", "records", "original_content"):
                continue
            # Convert bytes to base64 if needed
            if isinstance(value, bytes):
                import base64
                result[key] = {"_bytes": base64.b64encode(value).decode("ascii")}
            elif isinstance(value, (str, int, float, bool, type(None), list)):
                result[key] = value
            elif isinstance(value, dict):
                result[key] = self._make_serializable(value)
            else:
                # Skip other non-serializable types
                continue
        return result
    
    @property
    def is_redis(self) -> bool:
        """Check if using Redis backend."""
        return self._use_redis


# Global instance
_job_state: JobStateManager | None = None


def get_job_state() -> JobStateManager:
    """Get the global job state manager instance."""
    global _job_state
    if _job_state is None:
        _job_state = JobStateManager()
    return _job_state


def reset_job_state(redis_url: str | None = None) -> JobStateManager:
    """Reset the global job state manager (for testing)."""
    global _job_state
    _job_state = JobStateManager(redis_url)
    return _job_state

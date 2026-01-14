"""
Database operations for Lead Validator.
Uses SQLite for persistent job storage.
"""

import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from config import Config

# Current schema version - increment when making schema changes
SCHEMA_VERSION = 2

logger = logging.getLogger(__name__)


def get_connection() -> sqlite3.Connection:
    """Get a database connection with foreign keys enabled."""
    conn = sqlite3.connect(Config.DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def _get_schema_version(conn: sqlite3.Connection) -> int:
    """Get current schema version from database."""
    try:
        cursor = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        row = cursor.fetchone()
        return row[0] if row else 0
    except sqlite3.OperationalError:
        # Table doesn't exist yet
        return 0


def _run_migrations(conn: sqlite3.Connection, from_version: int) -> None:
    """Run database migrations from from_version to SCHEMA_VERSION."""
    # Migration from 0 -> 1: Initial schema (handled below in init_db)
    # Migration from 1 -> 2: Add last_heartbeat column
    if from_version < 2:
        cursor = conn.execute("PRAGMA table_info(jobs)")
        columns = [row[1] for row in cursor.fetchall()]
        if "last_heartbeat" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN last_heartbeat TEXT")
            logger.info("Migration: Added last_heartbeat column to jobs table")


def init_db() -> None:
    """Initialize database tables and run migrations if needed."""
    conn = get_connection()
    try:
        # Create schema_version table if not exists
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
        """
        )

        # Get current schema version
        current_version = _get_schema_version(conn)

        # Create main tables
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL,
                email_column TEXT,
                mode TEXT NOT NULL,
                total_rows INTEGER,
                summary_valid INTEGER DEFAULT 0,
                summary_risky INTEGER DEFAULT 0,
                summary_invalid INTEGER DEFAULT 0,
                avg_score REAL DEFAULT 0,
                top_risk_factors_json TEXT,
                error_message TEXT,
                last_heartbeat TEXT
            );

            CREATE TABLE IF NOT EXISTS job_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                row_index INTEGER NOT NULL,
                original_row_json TEXT,
                email TEXT,
                status TEXT,
                reason TEXT,
                score INTEGER,
                risk_factors TEXT,
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_job_results_job_id ON job_results(job_id);
            CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
        """
        )

        # Run migrations if needed
        if current_version < SCHEMA_VERSION:
            logger.info(
                f"Running database migrations from version {current_version} to {SCHEMA_VERSION}"
            )
            _run_migrations(conn, current_version)

            # Record new version
            conn.execute(
                "INSERT OR REPLACE INTO schema_version (version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, datetime.now(UTC).isoformat()),
            )
            logger.info(f"Database migrated to schema version {SCHEMA_VERSION}")

        conn.commit()
    finally:
        conn.close()


def save_job(job_data: dict[str, Any]) -> None:
    """Insert or update a job record."""
    conn = get_connection()
    try:
        # Check if job exists
        cursor = conn.execute("SELECT id FROM jobs WHERE id = ?", (job_data["id"],))
        exists = cursor.fetchone() is not None

        if exists:
            # Update only provided fields (partial update)
            update_fields = []
            update_values = []

            field_mapping = {
                "filename": "filename",
                "completed_at": "completed_at",
                "status": "status",
                "email_column": "email_column",
                "mode": "mode",
                "total_rows": "total_rows",
                "summary_valid": "summary_valid",
                "summary_risky": "summary_risky",
                "summary_invalid": "summary_invalid",
                "avg_score": "avg_score",
                "error_message": "error_message",
                "last_heartbeat": "last_heartbeat",
            }

            for key, db_field in field_mapping.items():
                if key in job_data:
                    update_fields.append(f"{db_field} = ?")
                    update_values.append(job_data[key])

            # Handle top_risk_factors specially (JSON)
            if "top_risk_factors" in job_data:
                update_fields.append("top_risk_factors_json = ?")
                update_values.append(json.dumps(job_data["top_risk_factors"]))

            if update_fields:
                update_values.append(job_data["id"])
                sql = f"UPDATE jobs SET {', '.join(update_fields)} WHERE id = ?"
                conn.execute(sql, update_values)
        else:
            # Insert new job
            now = datetime.now(UTC).isoformat()
            conn.execute(
                """
                INSERT INTO jobs (
                    id, filename, created_at, completed_at, status,
                    email_column, mode, total_rows,
                    summary_valid, summary_risky, summary_invalid,
                    avg_score, top_risk_factors_json, error_message,
                    last_heartbeat
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    job_data["id"],
                    job_data.get("filename"),
                    job_data.get("created_at", now),
                    job_data.get("completed_at"),
                    job_data.get("status", "running"),
                    job_data.get("email_column"),
                    job_data.get("mode"),
                    job_data.get("total_rows"),
                    job_data.get("summary_valid", 0),
                    job_data.get("summary_risky", 0),
                    job_data.get("summary_invalid", 0),
                    job_data.get("avg_score", 0),
                    json.dumps(job_data.get("top_risk_factors", [])),
                    job_data.get("error_message"),
                    job_data.get("last_heartbeat", now),  # Initialize heartbeat on creation
                ),
            )
        conn.commit()
    finally:
        conn.close()


def get_job(job_id: str) -> dict[str, Any] | None:
    """Get a job by ID."""
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        if not row:
            return None

        job = dict(row)
        # Parse JSON fields
        if job.get("top_risk_factors_json"):
            job["top_risk_factors"] = json.loads(job["top_risk_factors_json"])
        else:
            job["top_risk_factors"] = []
        del job["top_risk_factors_json"]
        return job
    finally:
        conn.close()


def list_jobs(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """List jobs ordered by created_at DESC."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        jobs = []
        for row in cursor.fetchall():
            job = dict(row)
            if job.get("top_risk_factors_json"):
                job["top_risk_factors"] = json.loads(job["top_risk_factors_json"])
            else:
                job["top_risk_factors"] = []
            del job["top_risk_factors_json"]
            jobs.append(job)
        return jobs
    finally:
        conn.close()


def delete_job(job_id: str) -> bool:
    """Delete a job and its results (cascade)."""
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def save_job_results(job_id: str, results: list[dict[str, Any]]) -> None:
    """Batch insert job results."""
    if not results:
        return

    conn = get_connection()
    try:
        # Delete existing results for this job first
        conn.execute("DELETE FROM job_results WHERE job_id = ?", (job_id,))

        # Insert new results
        conn.executemany(
            """
            INSERT INTO job_results (
                job_id, row_index, original_row_json, email,
                status, reason, score, risk_factors
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            [
                (
                    job_id,
                    r.get("row_index", i),
                    json.dumps(r.get("original_row", {})),
                    r.get("email"),
                    r.get("status"),
                    r.get("reason"),
                    r.get("score"),
                    r.get("risk_factors"),
                )
                for i, r in enumerate(results)
            ],
        )
        conn.commit()
    finally:
        conn.close()


def get_job_results(job_id: str, filter_type: str | None = None) -> list[dict[str, Any]]:
    """Get job results with optional filtering."""
    conn = get_connection()
    try:
        query = "SELECT * FROM job_results WHERE job_id = ?"
        params: list[Any] = [job_id]

        if filter_type == "valid":
            query += " AND status = 'valid'"
        elif filter_type == "risky":
            query += " AND status = 'risky'"
        elif filter_type == "risky_invalid":
            query += " AND status IN ('risky', 'invalid')"

        query += " ORDER BY row_index"

        cursor = conn.execute(query, params)
        results = []
        for row in cursor.fetchall():
            result = dict(row)
            if result.get("original_row_json"):
                result["original_row"] = json.loads(result["original_row_json"])
            else:
                result["original_row"] = {}
            del result["original_row_json"]
            results.append(result)
        return results
    finally:
        conn.close()


def cleanup_old_jobs(retention_days: int, max_jobs: int) -> int:
    """
    Delete old jobs beyond retention period and keep only max_jobs newest.
    Returns number of jobs deleted.
    """
    conn = get_connection()
    deleted_count = 0
    try:
        # Delete jobs older than retention_days
        cutoff_date = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        cursor = conn.execute(
            "DELETE FROM jobs WHERE created_at < ? AND status != 'running'",
            (cutoff_date,),
        )
        deleted_count += cursor.rowcount

        # Keep only max_jobs newest (delete oldest beyond limit)
        cursor = conn.execute(
            """
            DELETE FROM jobs WHERE id NOT IN (
                SELECT id FROM jobs ORDER BY created_at DESC LIMIT ?
            ) AND status != 'running'
        """,
            (max_jobs,),
        )
        deleted_count += cursor.rowcount

        conn.commit()
        return deleted_count
    finally:
        conn.close()


def get_job_count() -> int:
    """Get total number of jobs."""
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT COUNT(*) FROM jobs")
        return cursor.fetchone()[0]
    finally:
        conn.close()


def count_running_jobs() -> int:
    """Count jobs with status='running'."""
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'running'")
        return cursor.fetchone()[0]
    finally:
        conn.close()


def count_jobs_since(since_date: str, status: str | None = None) -> int:
    """
    Count jobs created since a given date.

    Args:
        since_date: ISO date string (e.g., "2024-01-15")
        status: Optional status filter

    Returns:
        Number of matching jobs
    """
    conn = get_connection()
    try:
        if status:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE created_at >= ? AND status = ?",
                (since_date, status),
            )
        else:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE created_at >= ?",
                (since_date,),
            )
        return cursor.fetchone()[0]
    finally:
        conn.close()


def update_job_heartbeat(job_id: str, timestamp: str | None = None) -> None:
    """
    Update job's last_heartbeat.

    Args:
        job_id: The job ID to update
        timestamp: Optional ISO timestamp. If None, uses current UTC time.
    """
    conn = get_connection()
    try:
        now = timestamp if timestamp else datetime.now(UTC).isoformat()
        conn.execute(
            "UPDATE jobs SET last_heartbeat = ? WHERE id = ?",
            (now, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_stalled_jobs(timeout_minutes: int) -> list[dict[str, Any]]:
    """
    Get jobs that haven't updated heartbeat within timeout.

    A job is considered stalled if:
    - status is 'running'
    - last_heartbeat is older than (now - timeout_minutes)
    - OR last_heartbeat is NULL and created_at is older than timeout

    Args:
        timeout_minutes: Number of minutes without heartbeat to consider stalled

    Returns:
        List of stalled job dictionaries
    """
    conn = get_connection()
    try:
        cutoff_time = (datetime.now(UTC) - timedelta(minutes=timeout_minutes)).isoformat()

        cursor = conn.execute(
            """
            SELECT * FROM jobs
            WHERE status = 'running'
            AND (
                (last_heartbeat IS NOT NULL AND last_heartbeat < ?)
                OR (last_heartbeat IS NULL AND created_at < ?)
            )
            """,
            (cutoff_time, cutoff_time),
        )

        jobs = []
        for row in cursor.fetchall():
            job = dict(row)
            if job.get("top_risk_factors_json"):
                job["top_risk_factors"] = json.loads(job["top_risk_factors_json"])
            else:
                job["top_risk_factors"] = []
            if "top_risk_factors_json" in job:
                del job["top_risk_factors_json"]
            jobs.append(job)
        return jobs
    finally:
        conn.close()

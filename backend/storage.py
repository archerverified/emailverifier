"""
File storage utilities for Lead Validator.
Handles upload storage, CSV generation, and ZIP bundling.

Security considerations:
- Job IDs are sanitized to prevent path traversal
- ZIP files use arcname to prevent absolute paths
- Output generation is idempotent
"""

import csv
import json
import logging
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

import db
from config import Config

logger = logging.getLogger(__name__)

# Pattern for valid job IDs (UUID format)
VALID_JOB_ID_PATTERN = re.compile(r"^[a-zA-Z0-9\-]+$")


def ensure_storage_dirs() -> None:
    """Create storage directories if they don't exist."""
    storage_dir = Path(Config.STORAGE_DIR)
    (storage_dir / "uploads").mkdir(parents=True, exist_ok=True)
    (storage_dir / "outputs").mkdir(parents=True, exist_ok=True)

    # Create .gitkeep files
    gitkeep_uploads = storage_dir / "uploads" / ".gitkeep"
    gitkeep_outputs = storage_dir / "outputs" / ".gitkeep"
    if not gitkeep_uploads.exists():
        gitkeep_uploads.touch()
    if not gitkeep_outputs.exists():
        gitkeep_outputs.touch()


def _sanitize_job_id(job_id: str) -> str | None:
    """
    Sanitize job ID to prevent path traversal.
    Returns None if job_id is invalid.
    """
    if not job_id:
        return None
    if not VALID_JOB_ID_PATTERN.match(job_id):
        logger.warning(f"Invalid job_id format: {job_id}")
        return None
    # Extra safety: ensure no path separators
    if "/" in job_id or "\\" in job_id or ".." in job_id:
        logger.warning(f"Path traversal attempt in job_id: {job_id}")
        return None
    return job_id


def get_upload_path(job_id: str) -> Path:
    """Get the path for a job's uploaded CSV."""
    safe_id = _sanitize_job_id(job_id)
    if not safe_id:
        raise ValueError(f"Invalid job_id: {job_id}")
    return Path(Config.STORAGE_DIR) / "uploads" / f"{safe_id}.csv"


def get_output_dir(job_id: str) -> Path:
    """Get the output directory for a job."""
    safe_id = _sanitize_job_id(job_id)
    if not safe_id:
        raise ValueError(f"Invalid job_id: {job_id}")
    return Path(Config.STORAGE_DIR) / "outputs" / safe_id


def save_upload(job_id: str, content: bytes) -> Path:
    """
    Save uploaded CSV content to disk.
    Returns the path to the saved file.
    """
    ensure_storage_dirs()
    upload_path = get_upload_path(job_id)
    upload_path.write_bytes(content)
    return upload_path


def get_upload_content(job_id: str) -> str | None:
    """Read the uploaded CSV content for a job."""
    upload_path = get_upload_path(job_id)
    if not upload_path.exists():
        return None
    try:
        return upload_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        try:
            return upload_path.read_text(encoding="latin-1")
        except Exception:
            return None


def generate_csv_outputs(job_id: str, force_regenerate: bool = False) -> bool:
    """
    Generate all 5 CSV output files from database results.
    Idempotent: reuses existing outputs unless force_regenerate=True.

    Args:
        job_id: The job ID
        force_regenerate: If True, regenerate even if outputs exist

    Returns:
        True if successful, False otherwise
    """
    job = db.get_job(job_id)
    if not job:
        return False

    try:
        output_dir = get_output_dir(job_id)
    except ValueError:
        return False

    # Check if all outputs already exist (unless forced)
    expected_files = ["all.csv", "valid.csv", "risky.csv", "risky_invalid.csv", "scores.csv"]
    if not force_regenerate and output_dir.exists():
        if all((output_dir / f).exists() for f in expected_files):
            logger.debug(f"Outputs already exist for job {job_id}, skipping regeneration")
            return True  # Already generated

    results = db.get_job_results(job_id)
    if not results:
        return False

    # Clean partial outputs before regenerating
    try:
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning(f"Could not prepare output directory for job {job_id}: {e}")
        return False

    # Get fieldnames from first result's original row
    if results and results[0].get("original_row"):
        original_keys = list(results[0]["original_row"].keys())
    else:
        original_keys = []

    fieldnames = original_keys + ["status", "reason", "score", "risk_factors"]

    # Generate each filter type
    filter_configs = [
        ("all", None),
        ("valid", "valid"),
        ("risky", "risky"),
        ("risky_invalid", "risky_invalid"),
    ]

    for filename_prefix, filter_type in filter_configs:
        if filter_type:
            filtered_results = db.get_job_results(job_id, filter_type)
        else:
            filtered_results = results

        if not filtered_results:
            # Create empty file with headers only
            output_path = output_dir / f"{filename_prefix}.csv"
            with open(output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
            continue

        output_path = output_dir / f"{filename_prefix}.csv"
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for result in filtered_results:
                row = dict(result.get("original_row", {}))
                row["status"] = result.get("status", "")
                row["reason"] = result.get("reason", "")
                row["score"] = result.get("score", "")
                row["risk_factors"] = result.get("risk_factors", "")
                writer.writerow(row)

    # Generate scores-only CSV
    scores_path = output_dir / "scores.csv"
    email_column = job.get("email_column", "email")
    with open(scores_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["email", "status", "reason", "score", "risk_factors"]
        )
        writer.writeheader()
        for result in results:
            original = result.get("original_row", {})
            writer.writerow(
                {
                    "email": original.get(email_column, result.get("email", "")),
                    "status": result.get("status", ""),
                    "reason": result.get("reason", ""),
                    "score": result.get("score", ""),
                    "risk_factors": result.get("risk_factors", ""),
                }
            )

    return True


def get_csv_output(job_id: str, filter_type: str) -> str | None:
    """
    Get CSV content for a specific filter type.
    Generates from DB if not on disk.
    """
    try:
        output_dir = get_output_dir(job_id)
    except ValueError:
        return None

    filename = f"{filter_type}.csv"
    output_path = output_dir / filename

    # Try to read from disk first
    if output_path.exists():
        return output_path.read_text(encoding="utf-8")

    # Generate outputs if they don't exist
    if generate_csv_outputs(job_id):
        if output_path.exists():
            return output_path.read_text(encoding="utf-8")

    return None


def generate_bundle_zip(job_id: str) -> Path | None:
    """
    Generate a ZIP bundle containing all CSVs and summary.json.
    Returns the path to the ZIP file, or None if job not found.

    Security:
    - Job ID is sanitized to prevent path traversal
    - ZIP entries use arcname to prevent absolute paths
    """
    # Validate job_id for path safety
    try:
        output_dir = get_output_dir(job_id)
    except ValueError:
        logger.warning(f"Invalid job_id for bundle: {job_id}")
        return None

    job = db.get_job(job_id)
    if not job:
        return None

    # Ensure CSV outputs exist
    if not (output_dir / "all.csv").exists():
        if not generate_csv_outputs(job_id):
            return None

    # Create summary.json
    summary = {
        "job_id": job_id,
        "filename": job.get("filename"),
        "created_at": job.get("created_at"),
        "completed_at": job.get("completed_at"),
        "status": job.get("status"),
        "mode": job.get("mode"),
        "total_rows": job.get("total_rows"),
        "summary": {
            "valid": job.get("summary_valid", 0),
            "risky": job.get("summary_risky", 0),
            "invalid": job.get("summary_invalid", 0),
            "avg_score": job.get("avg_score", 0),
            "top_risk_factors": job.get("top_risk_factors", []),
        },
    }

    summary_path = output_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    # Create ZIP bundle
    bundle_path = output_dir / "bundle.zip"
    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for csv_name in ["all.csv", "valid.csv", "risky.csv", "risky_invalid.csv", "scores.csv"]:
            csv_path = output_dir / csv_name
            if csv_path.exists():
                zf.write(csv_path, csv_name)
        zf.write(summary_path, "summary.json")

    return bundle_path


def delete_job_files(job_id: str) -> bool:
    """
    Delete all files associated with a job.
    Returns True if any files were deleted.
    """
    deleted = False

    try:
        # Delete upload
        upload_path = get_upload_path(job_id)
        if upload_path.exists():
            upload_path.unlink()
            deleted = True

        # Delete output directory
        output_dir = get_output_dir(job_id)
        if output_dir.exists():
            shutil.rmtree(output_dir)
            deleted = True
    except ValueError:
        logger.warning(f"Invalid job_id for deletion: {job_id}")
        return False

    return deleted


def get_storage_stats() -> dict[str, Any]:
    """Get storage usage statistics."""
    storage_dir = Path(Config.STORAGE_DIR)
    uploads_dir = storage_dir / "uploads"
    outputs_dir = storage_dir / "outputs"

    def get_dir_size(path: Path) -> int:
        total = 0
        if path.exists():
            for f in path.rglob("*"):
                if f.is_file():
                    total += f.stat().st_size
        return total

    return {
        "storage_dir": str(storage_dir),
        "uploads_size_bytes": get_dir_size(uploads_dir),
        "outputs_size_bytes": get_dir_size(outputs_dir),
        "total_size_bytes": get_dir_size(storage_dir),
        "job_count": db.get_job_count(),
    }

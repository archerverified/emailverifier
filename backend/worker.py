"""
RQ Worker for background email verification jobs.

This module handles the actual email verification work in a separate process,
enabling the API to return immediately while verification runs in the background.

Usage:
    rq worker --with-scheduler -c worker_settings
    
Or via the worker script:
    python -m rq.cli worker --with-scheduler -c worker_settings
"""

import csv
import io
import logging
import os
import sys
import time
from datetime import UTC, datetime

# Setup path for imports
sys.path.insert(0, os.path.dirname(__file__))

from config import Config
from job_state import get_job_state

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def process_verification_job(
    job_id: str,
    records: list[dict],
    email_field: str,
    filename: str,
    job_name: str,
    fieldnames: list[str],
) -> dict:
    """
    Process email verification job in background worker.
    
    Args:
        job_id: Unique job identifier
        records: List of CSV row dicts to process
        email_field: Name of the email column
        filename: Original filename
        job_name: User-provided job name
        fieldnames: CSV column names including result columns
        
    Returns:
        Job summary dict with statistics
    """
    # Import here to avoid circular imports and ensure fresh module state
    import csv_utils
    import db
    import storage
    from app import check_email, calculate_job_summary
    
    job_state = get_job_state()
    total = len(records)
    start_time = time.time()
    results_for_db: list[dict] = []
    
    # Create output buffer for CSV results
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    
    logger.info(f"Starting verification job {job_id}: {total} emails from {filename}")
    
    for i, row in enumerate(records, start=1):
        # Check for cancellation
        if job_state.is_cancelled(job_id):
            logger.info(f"Job {job_id} cancelled at row {i}")
            db.save_job({
                "id": job_id,
                "status": "cancelled",
                "completed_at": datetime.now(UTC).isoformat(),
            })
            return {"status": "cancelled", "processed": i - 1, "total": total}
        
        # Update processing_row before work
        job_state.update_job(job_id, {"processing_row": i})
        
        # Extract and normalize email
        email_raw = (row.get(email_field) or "").strip()
        if not email_raw:
            email = ""
            status, reason, score, risk_factors = "invalid", "empty_email", 0, ["empty_email"]
        else:
            email = csv_utils.extract_email_from_field(email_raw)
            email = csv_utils.normalize_email(email)
            
            if not email:
                status, reason, score, risk_factors = "invalid", "empty_email", 0, ["empty_email"]
            else:
                status, reason, score, risk_factors = check_email(email)
        
        # Update row with results
        row["status"] = status
        row["reason"] = reason
        row["score"] = str(score)
        row["risk_factors"] = "; ".join(risk_factors) if risk_factors else ""
        
        # Write to output
        writer.writerow(row)
        
        # Store for DB
        original_row = {k: v for k, v in row.items() 
                       if k not in ["status", "reason", "score", "risk_factors"]}
        results_for_db.append({
            "row_index": i - 1,
            "original_row": original_row,
            "email": email,
            "status": status,
            "reason": reason,
            "score": score,
            "risk_factors": "; ".join(risk_factors) if risk_factors else "",
        })
        
        # Update progress
        percent = int((i / total) * 100)
        job_state.update_progress(
            job_id=job_id,
            row=i,
            processing_row=i,
            percent=percent,
            log=f"✅ {email} → {status} (score:{score})",
        )
        
        # Heartbeat to DB every N rows
        if i % Config.JOB_HEARTBEAT_INTERVAL_ROWS == 0:
            db.update_job_heartbeat(job_id)
    
    # Calculate summary
    output.seek(0)
    reader = list(csv.DictReader(output))
    
    valid_count = sum(1 for r in reader if r.get("status") == "valid")
    risky_count = sum(1 for r in reader if r.get("status") == "risky")
    invalid_count = sum(1 for r in reader if r.get("status") == "invalid")
    
    total_score = 0
    for r in reader:
        try:
            total_score += int(r.get("score", 0))
        except (ValueError, TypeError):
            pass
    
    avg_score = round(total_score / total, 1) if total > 0 else 0
    
    summary = {
        "valid": valid_count,
        "risky": risky_count,
        "invalid": invalid_count,
        "total": total,
        "avg_score": avg_score,
    }
    
    # Update job state with summary
    job_state.update_job(job_id, {
        "progress": 100,
        "row": total,
        "processing_row": total,
        "summary": summary,
    })
    
    # Save results to DB
    db.save_job_results(job_id, results_for_db)
    
    # Update job status
    elapsed_ms = int((time.time() - start_time) * 1000)
    db.save_job({
        "id": job_id,
        "completed_at": datetime.now(UTC).isoformat(),
        "status": "completed",
        "summary_valid": valid_count,
        "summary_risky": risky_count,
        "summary_invalid": invalid_count,
        "avg_score": avg_score,
    })
    
    # Generate CSV output files
    storage.generate_csv_outputs(job_id)
    
    logger.info(f"Job {job_id} completed: {valid_count} valid, {risky_count} risky, "
                f"{invalid_count} invalid ({elapsed_ms}ms)")
    
    return summary


# RQ worker settings (imported by rq worker -c worker_settings)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
QUEUES = ["default", "high", "low"]

# Lead Validator Backend - Email Verification API
# Flask API that verifies emails via syntax + disposable/role checks + MX + SMTP

import csv
import io
import json
import logging
import random
import re
import smtplib
import socket
import sys
import threading
import time
import uuid
from collections import Counter
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps
from tempfile import NamedTemporaryFile

import dns.resolver
from flask import Flask, Response, g, jsonify, request, send_file, send_from_directory
from flask_cors import CORS

import csv_utils
import db
import dns_cache
import rate_limiter
import storage
from config import Config

# Request ID context for structured logging
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")


# Structured logging formatter
class StructuredFormatter(logging.Formatter):
    """Key=value structured logging formatter for readability on all consoles."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
        }

        # Add request ID if available
        req_id = request_id_ctx.get("")
        if req_id:
            log_data["request_id"] = req_id

        # Add extra fields from record
        extra_fields = [
            "job_id",
            "file_name",
            "elapsed_ms",
            "mode",
            "job_status",
            "row_count",
            "max_upload_mb",
        ]
        for field in extra_fields:
            if hasattr(record, field):
                log_data[field] = getattr(record, field)

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Format as key=value for readability
        parts = [f"{k}={json.dumps(v) if isinstance(v, str) else v}" for k, v in log_data.items()]
        return " ".join(parts)


# Setup logger
logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, Config.LOG_LEVEL))
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(StructuredFormatter())
logger.addHandler(handler)

# Create Flask app with configuration
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = Config.MAX_CONTENT_LENGTH

# Configure CORS - restrictive by default
cors_origins = Config.get_cors_origins()
if cors_origins:
    CORS(app, origins=cors_origins)
    logger.info(f"CORS enabled for origins: {cors_origins}")
else:
    # Same-origin only - initialize CORS for local dev but restrictive
    CORS(app, origins=["http://localhost:3000", "http://localhost:5050", "http://127.0.0.1:5050"])
    logger.info("CORS enabled for localhost development only")

# Initialize storage and database
storage.ensure_storage_dirs()
db.init_db()
cleanup_count = db.cleanup_old_jobs(Config.RETENTION_DAYS, Config.MAX_JOBS)
if cleanup_count > 0:
    logger.info(f"Cleaned up {cleanup_count} old jobs on startup")

# Initialize DNS cache (process-lifetime with TTL)
mx_cache = dns_cache.DNSCache(Config.DNS_CACHE_TTL_MINUTES)

# SMTP concurrency control (semaphores)
smtp_global_semaphore = threading.Semaphore(Config.SMTP_GLOBAL_WORKERS)
domain_semaphores: dict[str, threading.Semaphore] = {}
domain_semaphores_lock = threading.Lock()


def get_domain_semaphore(domain: str) -> threading.Semaphore:
    """Get or create a semaphore for a specific domain (per-domain concurrency limit)."""
    domain_lower = domain.lower()
    with domain_semaphores_lock:
        if domain_lower not in domain_semaphores:
            domain_semaphores[domain_lower] = threading.Semaphore(Config.SMTP_PER_DOMAIN_LIMIT)
        return domain_semaphores[domain_lower]


# Startup message
logger.info(
    "Verifier started",
    extra={"mode": Config.VALIDATOR_MODE, "max_upload_mb": Config.MAX_UPLOAD_MB},
)
print(
    f">>> LEAD VALIDATOR (mode={Config.VALIDATOR_MODE}) "
    f"- Email Verification Service • Version {Config.VERSION} <<<"
)


# ============================================================================
# Job Monitor (Stall Detection with Clean Lifecycle)
# ============================================================================

import atexit  # noqa: E402

import job_monitor  # noqa: E402

# Start job health monitoring (disabled in TESTING mode)
job_monitor.start_monitor()


def cleanup_on_exit() -> None:
    """Clean shutdown of background services."""
    logger.debug("Shutting down background services...")
    job_monitor.stop_monitor()


atexit.register(cleanup_on_exit)


def get_running_jobs_count() -> int:
    """
    Get count of currently running jobs.
    Combines in-memory active jobs with database running jobs.
    """
    with data_lock:
        # Count in-memory jobs that are still processing
        memory_count = sum(
            1 for job in data.values() if job.get("progress", 0) < 100 and not job.get("cancel")
        )

    # Get DB count of running jobs
    db_count = db.count_running_jobs()

    # Use the higher of the two (covers edge cases during startup/restart)
    return max(memory_count, db_count)


# Email validation patterns
EMAIL_REGEX = re.compile(r"[^@]+@[^@]+\.[^@]+")
DISPOSABLE_DOMAINS = {"mailinator.com", "10minutemail.com", "guerrillamail.com"}
ROLE_BASED_PREFIXES = {"info", "support", "admin", "sales", "contact"}

# Email column detection patterns (case-insensitive)
EMAIL_COLUMN_EXACT = {"email", "e-mail", "e_mail", "emailaddress", "email_address"}
EMAIL_COLUMN_CONTAINS = {"email", "e-mail", "mail"}

# Thread-safe job data storage
data: dict = {}
data_lock = threading.Lock()


# Request ID middleware
@app.before_request
def set_request_id() -> None:
    """Set request ID from header or generate new one."""
    req_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request_id_ctx.set(req_id)
    g.request_id = req_id


@app.after_request
def add_request_id_header(response: Response) -> Response:
    """Add request ID to response headers."""
    if hasattr(g, "request_id"):
        response.headers["X-Request-ID"] = g.request_id
    return response


# Exception handler
@app.errorhandler(Exception)
def handle_exception(e: Exception) -> tuple[Response, int]:
    """Log exceptions and return safe error response."""
    logger.exception("Unhandled exception", exc_info=e)
    return jsonify({"error": "Internal server error"}), 500


@app.errorhandler(413)
def handle_too_large(e: Exception) -> tuple[Response, int]:
    """Handle file too large error."""
    max_mb = Config.MAX_UPLOAD_MB
    return error_response(
        code="FILE_TOO_LARGE",
        message=f"File too large. Maximum size is {max_mb}MB",
        details={"max_upload_mb": max_mb},
        status_code=413,
    )


def error_response(
    code: str,
    message: str,
    details: dict | None = None,
    status_code: int = 400,
) -> tuple[Response, int]:
    """
    Create a structured error response.

    Args:
        code: Error code (e.g., "INVALID_CSV", "TOO_MANY_JOBS")
        message: Human-readable message
        details: Optional additional details
        status_code: HTTP status code
    """
    payload: dict = {
        "error": {
            "code": code,
            "message": message,
        },
        "request_id": g.get("request_id", "unknown"),
    }
    if details:
        payload["error"]["details"] = details

    return jsonify(payload), status_code


# ============================================================================
# API Key Authentication Decorator
# ============================================================================


def require_api_key(f):
    """
    Decorator to require API key for protected endpoints.
    If APP_API_KEY is not set, allows all requests (backward compat for dev).
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        # If no API key configured, allow all requests (dev mode)
        if not Config.APP_API_KEY:
            return f(*args, **kwargs)

        provided_key = request.headers.get("X-API-Key", "")
        if provided_key != Config.APP_API_KEY:
            logger.warning(
                "Unauthorized API access attempt",
                extra={"job_id": "auth", "mode": "rejected"},
            )
            return error_response(
                "UNAUTHORIZED",
                "Invalid or missing API key",
                {"hint": "Provide valid X-API-Key header"},
                401,
            )
        return f(*args, **kwargs)

    return decorated


# ============================================================================
# Rate Limiting Decorator
# ============================================================================


def rate_limit(f):
    """
    Decorator to apply rate limiting to endpoints.
    Uses dual-strategy: per-IP and per-API-key limits.
    Disabled in testing mode.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        # Disable rate limiting in testing mode
        if Config.TESTING:
            return f(*args, **kwargs)

        # Get client IP (handle proxies)
        client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
        if client_ip and "," in client_ip:
            client_ip = client_ip.split(",")[0].strip()

        # Get API key if provided
        api_key = request.headers.get("X-API-Key", None)

        # Check rate limit
        allowed, reason, details = rate_limiter.rate_limiter.is_allowed(
            ip=client_ip or "unknown",
            api_key=api_key,
            ip_limit=Config.RATE_LIMIT_IP_PER_MINUTE,
            key_limit=Config.RATE_LIMIT_KEY_PER_MINUTE,
            window=60,
        )

        if not allowed:
            logger.warning(
                "Rate limit exceeded",
                extra={"job_id": "rate_limit", "mode": reason},
            )
            return error_response(
                "RATE_LIMIT_EXCEEDED",
                reason,
                details,
                429,
            )

        return f(*args, **kwargs)

    return decorated


def validate_csv_content(content: str) -> tuple[bool, str]:
    """
    Validate CSV content for safety.
    Returns (is_valid, error_message).
    """
    lines = content.split("\n")

    # Check for empty file
    if len(lines) < 2:
        return False, "CSV file must have at least a header and one data row"

    # Check for too many rows
    if len(lines) > Config.MAX_CSV_ROWS:
        return False, f"CSV file exceeds maximum of {Config.MAX_CSV_ROWS} rows"

    # Check for extremely long lines (potential DOS)
    for i, line in enumerate(lines[:100], 1):  # Check first 100 lines
        if len(line) > Config.MAX_LINE_LENGTH:
            return (
                False,
                f"Line {i} exceeds maximum length of {Config.MAX_LINE_LENGTH} characters",
            )

    # Check header is not blank
    header = lines[0].strip()
    if not header:
        return False, "CSV header row is blank"

    return True, ""


def detect_email_columns(headers: list[str]) -> list[str]:
    """
    Detect candidate email columns from CSV headers.
    Returns list of column names that look like email columns.
    """
    candidates = []
    for header in headers:
        header_lower = header.lower().strip()
        header_normalized = header_lower.replace(" ", "").replace("-", "").replace("_", "")

        # Exact matches (normalized)
        if header_normalized in EMAIL_COLUMN_EXACT:
            candidates.append(header)
            continue

        # Contains email-related terms
        for pattern in EMAIL_COLUMN_CONTAINS:
            if pattern in header_lower:
                candidates.append(header)
                break

    return candidates


def calculate_score_and_risks(email: str, status: str, reason: str) -> tuple[int, list[str]]:
    """
    Calculate confidence score (0-100) and risk factors for an email.
    Returns (score, risk_factors).
    """
    score = 100
    risk_factors: list[str] = []
    domain = email.split("@")[1].lower() if "@" in email else ""

    # Critical failures - score 0
    if reason in ("bad_syntax", "empty_email"):
        return 0, ["invalid_syntax"]
    if reason in ("no_mx", "no_mx_dns_timeout"):
        return 0, ["no_mail_server"]
    if reason.startswith("smtp_reject"):
        return 0, ["mailbox_not_found"]
    if reason == "disposable_domain":
        return 0, ["disposable_provider"]

    # Role-based emails
    if reason == "role_based":
        score -= 25
        risk_factors.append("role_based_email")

    # SMTP timeout issues (including retry-enhanced reasons)
    if reason in ("smtp_timeout", "timeout_after_retry"):
        score -= 25
        risk_factors.append("smtp_unreachable")

    # Connection errors
    if reason in ("connection_refused", "connection_reset"):
        score -= 30
        risk_factors.append("smtp_connection_failed")

    # Temporary SMTP failures (4xx codes)
    if reason.startswith("smtp_soft_fail") or reason.startswith("temp_fail_"):
        score -= 25
        risk_factors.append("temporary_smtp_failure")

    # Other SMTP errors
    if reason.startswith("smtp_") and reason not in ("smtp_ok", "smtp_timeout"):
        if "soft_fail" not in reason and "reject" not in reason:
            score -= 30
            risk_factors.append("smtp_error")

    # Catch-all domains
    if reason == "domain_accepts_all":
        score -= 15
        risk_factors.append("catch_all_domain")

    # Mock mode risky
    if reason == "mock_risky":
        score -= 40
        risk_factors.append("unverifiable_domain")

    # Free email providers (minor penalty, can still be valid)
    if domain in Config.FREE_EMAIL_PROVIDERS:
        score -= 5
        risk_factors.append("free_email_provider")

    # Clamp score
    score = max(0, min(100, score))
    return score, risk_factors


def check_email_mock(email: str) -> tuple[str, str, int, list[str]]:
    """
    Deterministic mock email validation for testing.
    No network calls - uses simple rules for predictable results.
    Returns (status, reason, score, risk_factors).
    """
    if not EMAIL_REGEX.match(email):
        return "invalid", "bad_syntax", 0, ["invalid_syntax"]

    domain = email.split("@")[1].lower()
    local = email.split("@")[0].lower()

    # Check disposable domains
    if domain in DISPOSABLE_DOMAINS:
        return "invalid", "disposable_domain", 0, ["disposable_provider"]

    # Check role-based prefixes
    if local in ROLE_BASED_PREFIXES:
        return "risky", "role_based", 75, ["role_based_email"]

    # Deterministic rules for testing
    if domain in ["example.com", "example.org", "test.com"]:
        score = 95
        factors: list[str] = []
        if domain in Config.FREE_EMAIL_PROVIDERS:
            score -= 5
            factors.append("free_email_provider")
        return "valid", "mock_valid", score, factors

    if domain.endswith(".edu") or domain.endswith(".gov"):
        return "valid", "mock_valid", 95, []

    # Free email providers
    if domain in Config.FREE_EMAIL_PROVIDERS:
        return "valid", "mock_valid", 95, ["free_email_provider"]

    # All other domains are risky in mock mode
    return "risky", "mock_risky", 60, ["unverifiable_domain"]


def _jittered_backoff() -> float:
    """Return backoff time with jitter (RETRY_BACKOFF_MS +/- 300ms)."""
    base_ms = Config.RETRY_BACKOFF_MS
    jitter_ms = random.randint(-300, 300)
    return max(100, base_ms + jitter_ms) / 1000.0  # Convert to seconds, minimum 100ms


def _single_smtp_check(email: str, mx_record: str, timeout: int) -> tuple[int | None, str]:
    """
    Single SMTP check attempt.
    Returns (code, detail) where detail describes what happened.
    """
    try:
        server = smtplib.SMTP(timeout=timeout)
        server.connect(mx_record)
        server.helo("example.com")
        server.mail("verifier@example.com")
        code, _ = server.rcpt(email)
        server.quit()
        return code, "success"
    except (socket.timeout, TimeoutError):
        return None, "timeout"
    except ConnectionResetError:
        return None, "connection_reset"
    except ConnectionRefusedError:
        return None, "connection_refused"
    except OSError as e:
        # Handle network-level errors (e.g., host unreachable)
        return None, f"os_error_{type(e).__name__}"
    except smtplib.SMTPException as e:
        return None, f"smtp_exception_{type(e).__name__}"
    except Exception as e:
        return None, f"error_{type(e).__name__}"


def _smtp_check_with_retry(email: str, mx_record: str) -> tuple[int | None, str]:
    """
    Perform SMTP check with retry on timeout/4xx temporary failures.
    Returns (code, detailed_reason).
    """
    last_code: int | None = None
    last_detail: str = "unknown"

    for attempt in range(Config.SMTP_RETRIES + 1):
        code, detail = _single_smtp_check(email, mx_record, Config.SMTP_TIMEOUT_SECONDS)

        # Success - valid email
        if code == 250:
            return code, "smtp_ok"

        # Hard reject (5xx user unknown) - don't retry
        if code in (550, 551, 552, 553, 554):
            return code, f"smtp_reject_{code}"

        # Track last result for final reporting
        last_code = code
        last_detail = detail

        # Check if we should retry
        is_retryable = code is None or code in (  # Timeout or connection error
            421,
            450,
            451,
            452,
        )  # Temporary 4xx failures

        if is_retryable and attempt < Config.SMTP_RETRIES:
            time.sleep(_jittered_backoff())
            continue

        # Last attempt or non-retryable - return result
        break

    # Determine final reason based on last result
    if last_code is None:
        # Connection/timeout failure
        if last_detail == "timeout":
            return None, "timeout_after_retry" if Config.SMTP_RETRIES > 0 else "smtp_timeout"
        elif last_detail == "connection_refused":
            return None, "connection_refused"
        elif last_detail == "connection_reset":
            return None, "connection_reset"
        else:
            return None, f"connection_error_{last_detail}"

    if last_code in (421, 450, 451, 452):
        suffix = "_after_retry" if Config.SMTP_RETRIES > 0 else ""
        return last_code, f"temp_fail_{last_code}{suffix}"

    # Other codes
    return last_code, f"smtp_{last_code}"


def _smtp_check_catch_all(mx_record: str, domain: str) -> bool:
    """
    Check if domain accepts all emails (catch-all).
    Returns True if domain is catch-all, False otherwise.
    """
    try:
        server = smtplib.SMTP(timeout=Config.SMTP_TIMEOUT_SECONDS)
        server.connect(mx_record)
        server.helo("example.com")
        server.mail("probe@example.com")
        code, _ = server.rcpt(f"doesnotexist123abc789xyz@{domain}")
        server.quit()
        return code == 250
    except Exception:
        return False


def check_email(email: str) -> tuple[str, str, int, list[str]]:
    """
    Validate an email address through multiple checks:
    - Syntax validation
    - Disposable domain check
    - Role-based prefix check
    - MX record lookup (with caching)
    - SMTP verification (with concurrency control and retries)

    In mock mode, uses deterministic rules without network calls.
    Returns (status, reason, score, risk_factors).
    """
    # Use mock mode for testing
    if Config.VALIDATOR_MODE == "mock":
        return check_email_mock(email)

    # Real validation below
    if not EMAIL_REGEX.match(email):
        return "invalid", "bad_syntax", 0, ["invalid_syntax"]

    domain = email.split("@")[1]
    local = email.split("@")[0]

    if domain.lower() in DISPOSABLE_DOMAINS:
        return "invalid", "disposable_domain", 0, ["disposable_provider"]
    if local.lower() in ROLE_BASED_PREFIXES:
        score, factors = calculate_score_and_risks(email, "risky", "role_based")
        return "risky", "role_based", score, factors

    # DNS/MX lookup with caching
    mx_records = mx_cache.get_mx(domain)
    if mx_records is None:
        try:
            resolver = dns.resolver.Resolver()
            resolver.lifetime = Config.DNS_TIMEOUT_SECONDS
            records = resolver.resolve(domain, "MX")
            mx_records = [str(r.exchange) for r in records]
            mx_cache.set_mx(domain, mx_records)
        except dns.resolver.NXDOMAIN:
            mx_cache.set_negative(domain)
            return "invalid", "no_mx", 0, ["no_mail_server"]
        except dns.resolver.NoAnswer:
            mx_cache.set_negative(domain)
            return "invalid", "no_mx", 0, ["no_mail_server"]
        except dns.resolver.Timeout:
            return "invalid", "no_mx_dns_timeout", 0, ["no_mail_server"]
        except Exception:
            return "invalid", "no_mx", 0, ["no_mail_server"]

    # Check if cached negative result
    if not mx_records:
        return "invalid", "no_mx", 0, ["no_mail_server"]

    mx_record = mx_records[0]

    # SMTP checks with concurrency control
    # Acquire global semaphore first, then per-domain
    with smtp_global_semaphore:
        domain_sem = get_domain_semaphore(domain)
        with domain_sem:
            # Check for catch-all domain
            if _smtp_check_catch_all(mx_record, domain):
                score, factors = calculate_score_and_risks(email, "risky", "domain_accepts_all")
                return "risky", "domain_accepts_all", score, factors

            # Main SMTP verification with retry logic
            code, reason = _smtp_check_with_retry(email, mx_record)

    # Process result
    if code == 250:
        score, factors = calculate_score_and_risks(email, "valid", reason)
        return "valid", reason, score, factors
    elif code is None:
        # Timeout or connection failure
        score, factors = calculate_score_and_risks(email, "risky", reason)
        return "risky", reason, score, factors
    elif code in (421, 450, 451, 452):
        # Temporary failure persisted after retries
        score, factors = calculate_score_and_risks(email, "risky", reason)
        return "risky", reason, score, factors
    elif code in (550, 551, 552, 553, 554):
        # Hard reject
        return "invalid", reason, 0, ["mailbox_not_found"]
    else:
        # Other SMTP codes
        score, factors = calculate_score_and_risks(email, "invalid", reason)
        return "invalid", reason, score, factors


def calculate_job_summary(job_data: dict) -> dict:
    """Calculate summary statistics for a completed job."""
    job_data["output"].seek(0)
    reader = list(csv.DictReader(job_data["output"]))

    valid_count = 0
    risky_count = 0
    invalid_count = 0
    total_score = 0
    all_risk_factors: list[str] = []

    for row in reader:
        status = row.get("status", "")
        if status == "valid":
            valid_count += 1
        elif status == "risky":
            risky_count += 1
        elif status == "invalid":
            invalid_count += 1

        # Parse score
        try:
            score = int(row.get("score", 0))
            total_score += score
        except (ValueError, TypeError):
            pass

        # Collect risk factors
        factors_str = row.get("risk_factors", "")
        if factors_str:
            all_risk_factors.extend(factors_str.split("; "))

    # Calculate averages and top factors
    total_rows = len(reader)
    avg_score = round(total_score / total_rows, 1) if total_rows > 0 else 0

    # Get top 5 risk factors
    factor_counts = Counter(all_risk_factors)
    top_factors = [factor for factor, _ in factor_counts.most_common(5)]

    return {
        "valid": valid_count,
        "risky": risky_count,
        "invalid": invalid_count,
        "avg_score": avg_score,
        "top_risk_factors": top_factors,
    }


@app.route("/verify", methods=["POST"])
@require_api_key
@rate_limit
def verify() -> tuple[Response, int] | Response:
    """
    Upload a CSV file and start email verification job.
    Returns job_id for tracking progress.

    Optional form fields:
    - email_column: specify which column contains emails
    - job_name: custom name for the job (defaults to filename)
    - delimiter: CSV delimiter (auto-detected if not provided)
    """
    # Check concurrency limit FIRST
    running = get_running_jobs_count()
    if running >= Config.MAX_CONCURRENT_JOBS:
        logger.warning(
            "Concurrent job limit reached",
            extra={"running_jobs": running, "max_allowed": Config.MAX_CONCURRENT_JOBS},
        )
        return error_response(
            code="TOO_MANY_CONCURRENT_JOBS",
            message=(
                f"Maximum {Config.MAX_CONCURRENT_JOBS} concurrent jobs allowed. "
                f"Currently running: {running}. Please wait for a job to complete."
            ),
            details={
                "running_jobs": running,
                "max_allowed": Config.MAX_CONCURRENT_JOBS,
            },
            status_code=429,
        )

    # Validate file presence
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    # Validate file extension
    if not file.filename.lower().endswith(".csv"):
        return jsonify({"error": "File must be a CSV"}), 400

    try:
        # Read and decode CSV with UTF-8 BOM support
        content = file.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            # Fallback to latin-1 encoding
            file.seek(0)
            content = file.read().decode("latin-1")
        except Exception as e:
            return jsonify({"error": f"Failed to decode file: {str(e)}"}), 400

    # Validate CSV content for safety
    is_valid, error_msg = validate_csv_content(content)
    if not is_valid:
        return jsonify({"error": error_msg}), 400

    # Get optional delimiter from form data, or auto-detect
    delimiter = request.form.get("delimiter")
    if not delimiter:
        delimiter = csv_utils.detect_delimiter(content)
        logger.info(f"Auto-detected delimiter: {repr(delimiter)}")

    try:
        reader = list(csv.DictReader(io.StringIO(content), delimiter=delimiter))
    except Exception as e:
        return jsonify({"error": f"Failed to parse CSV: {str(e)}"}), 400

    # Validate CSV has data
    if not reader:
        return jsonify({"error": "CSV file is empty"}), 400

    available_columns = list(reader[0].keys())

    # Get optional email_column from form data
    email_column = request.form.get("email_column")
    job_name = request.form.get("job_name", file.filename)

    if email_column:
        # Validate provided column exists
        if email_column not in available_columns:
            return error_response(
                code="COLUMN_NOT_FOUND",
                message=f"Column '{email_column}' not found in CSV",
                details={
                    "available_columns": available_columns,
                    "email_column_candidates": detect_email_columns(available_columns),
                },
                status_code=400,
            )
        email_field = email_column
    else:
        # Auto-detect email column
        candidates = detect_email_columns(available_columns)

        if len(candidates) == 0:
            return error_response(
                code="NO_EMAIL_COLUMN",
                message="No email column found. Please specify email_column.",
                details={
                    "available_columns": available_columns,
                    "email_column_candidates": [],
                },
                status_code=400,
            )
        elif len(candidates) == 1:
            email_field = candidates[0]
        else:
            # Multiple candidates - require user selection
            return error_response(
                code="MULTIPLE_EMAIL_COLUMNS",
                message="Multiple email columns detected. Please specify email_column.",
                details={
                    "available_columns": available_columns,
                    "email_column_candidates": candidates,
                },
                status_code=400,
            )

    job_id = str(uuid.uuid4())
    total = len(reader)

    output = io.StringIO()
    fieldnames = list(reader[0].keys()) + ["status", "reason", "score", "risk_factors"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    # Store original content bytes for persistence
    original_content = content.encode("utf-8")

    with data_lock:
        # #region agent log
        import os, json
        with open(r'c:\Users\OxGh0\OneDrive\Desktop\Email Verifier Warp\Email Verifier Warp\.cursor\debug.log', 'a', encoding='utf-8') as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"pre-fix","hypothesisId":"H2","location":"app.py:881","message":"job created in worker memory","data":{"job_id":job_id,"worker_pid":os.getpid(),"total_rows":total},"timestamp":int(__import__('time').time()*1000)})+'\n')
        # #endregion
    # #region agent log
    # Secondary debug sink for Linux/Docker deployments (inside container volume).
    # Do not log secrets (API keys, emails, etc).
    try:
        with open("/app/storage/debug.log", "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "sessionId": "debug-session",
                        "runId": "pre-fix",
                        "hypothesisId": "H2",
                        "location": "app.py:881",
                        "message": "job created in worker memory (docker sink)",
                        "data": {
                            "job_id": job_id,
                            "worker_pid": os.getpid(),
                            "total_rows": total,
                        },
                        "timestamp": int(__import__("time").time() * 1000),
                    }
                )
                + "\n"
            )
    except Exception:
        pass
    # #endregion
        data[job_id] = {
            "progress": 0,
            "row": 0,
            "total": total,
            "log": "",
            "cancel": False,
            "output": output,
            "writer": writer,
            "records": reader,
            "email_field": email_field,
            "filename": file.filename,
            "job_name": job_name,
            "temp_file": None,
            "start_time": time.time(),
            "summary": None,
            "original_content": original_content,
        }

    # Log job creation
    logger.info(
        "Job created",
        extra={
            "job_id": job_id,
            "file_name": file.filename,
            "row_count": total,
            "mode": Config.VALIDATOR_MODE,
        },
    )

    # Persist job to database
    db.save_job(
        {
            "id": job_id,
            "filename": file.filename,
            "created_at": datetime.now(UTC).isoformat(),
            "status": "running",
            "email_column": email_field,
            "mode": Config.VALIDATOR_MODE,
            "total_rows": total,
        }
    )

    # Save upload to disk
    storage.save_upload(job_id, original_content)

    def run() -> None:
        start_time = time.time()
        results_for_db: list[dict] = []

        for i, row in enumerate(reader, start=1):
            with data_lock:
                if job_id not in data:
                    # Job was cleared (e.g., by test fixture)
                    break
                if data[job_id]["cancel"]:
                    data[job_id]["log"] = f"\u274c Canceled job {job_id}"
                    logger.info(
                        "Job cancelled",
                        extra={"job_id": job_id, "job_status": "cancelled", "row_count": i - 1},
                    )
                    # Update DB status to cancelled
                    db.save_job(
                        {
                            "id": job_id,
                            "status": "cancelled",
                            "completed_at": datetime.now(UTC).isoformat(),
                        }
                    )
                    break

            # Extract and normalize email
            email_raw = (row.get(email_field) or "").strip()
            if not email_raw:
                email = ""
                status, reason, score, risk_factors = "invalid", "empty_email", 0, ["empty_email"]
            else:
                # Extract email from angle-bracket format like "Name <email@domain.com>"
                email = csv_utils.extract_email_from_field(email_raw)
                # Normalize: lowercase domain, strip whitespace
                email = csv_utils.normalize_email(email)

                if not email:
                    status, reason, score, risk_factors = (
                        "invalid",
                        "empty_email",
                        0,
                        ["empty_email"],
                    )
                else:
                    status, reason, score, risk_factors = check_email(email)

            # Update heartbeat every N rows
            if i % Config.JOB_HEARTBEAT_INTERVAL_ROWS == 0:
                db.update_job_heartbeat(job_id)

            row["status"] = status
            row["reason"] = reason
            row["score"] = str(score)
            row["risk_factors"] = "; ".join(risk_factors) if risk_factors else ""

            # Store result for database persistence
            original_row = {
                k: v
                for k, v in row.items()
                if k not in ["status", "reason", "score", "risk_factors"]
            }
            results_for_db.append(
                {
                    "row_index": i - 1,
                    "original_row": original_row,
                    "email": email,
                    "status": status,
                    "reason": reason,
                    "score": score,
                    "risk_factors": "; ".join(risk_factors) if risk_factors else "",
                }
            )

            with data_lock:
                data[job_id]["writer"].writerow(row)
                percent = int((i / total) * 100)
                # #region agent log
                if i % 5 == 0:  # Log every 5 rows to avoid spam
                    import os, json
                    with open(r'c:\Users\OxGh0\OneDrive\Desktop\Email Verifier Warp\Email Verifier Warp\.cursor\debug.log', 'a', encoding='utf-8') as f:
                        f.write(json.dumps({"sessionId":"debug-session","runId":"pre-fix","hypothesisId":"H2","location":"app.py:1007","message":"progress updated in worker","data":{"job_id":job_id,"worker_pid":os.getpid(),"row":i,"percent":percent,"total":total},"timestamp":int(__import__('time').time()*1000)})+'\n')
                # #endregion
                # #region agent log
                if i % 5 == 0:
                    try:
                        with open("/app/storage/debug.log", "a", encoding="utf-8") as f:
                            f.write(
                                json.dumps(
                                    {
                                        "sessionId": "debug-session",
                                        "runId": "pre-fix",
                                        "hypothesisId": "H2",
                                        "location": "app.py:1007",
                                        "message": "progress updated in worker (docker sink)",
                                        "data": {
                                            "job_id": job_id,
                                            "worker_pid": os.getpid(),
                                            "row": i,
                                            "percent": percent,
                                            "total": total,
                                        },
                                        "timestamp": int(__import__("time").time() * 1000),
                                    }
                                )
                                + "\n"
                            )
                    except Exception:
                        pass
                # #endregion
                data[job_id].update(
                    {
                        "progress": percent,
                        "row": i,
                        "log": f"\u2705 {email} \u2192 {status} (score:{score})",
                    }
                )

        # Save to temp file for downloads and calculate summary
        with data_lock:
            output = data[job_id]["output"]
            output.seek(0)
            temp = NamedTemporaryFile(delete=False, suffix=".csv", mode="w+", encoding="utf-8")
            temp.write(output.read())
            temp.flush()
            temp.close()
            data[job_id]["temp_file"] = temp.name

            # Calculate summary statistics
            is_cancelled = data[job_id]["cancel"]
            if not is_cancelled:
                data[job_id]["summary"] = calculate_job_summary(data[job_id])

            # Log job completion
            elapsed_ms = int((time.time() - start_time) * 1000)
            job_filename = data[job_id].get("filename", "unknown") if job_id in data else "unknown"
            if not is_cancelled:
                logger.info(
                    "Job completed",
                    extra={
                        "job_id": job_id,
                        "file_name": job_filename,
                        "row_count": total,
                        "elapsed_ms": elapsed_ms,
                        "job_status": "completed",
                    },
                )

        # Persist results to database and generate output files
        if not is_cancelled:
            # Save results to database
            db.save_job_results(job_id, results_for_db)

            # Get summary for DB update (may be cleared by test fixture)
            with data_lock:
                job_data = data.get(job_id, {})
                summary = job_data.get("summary", {}) if job_data else {}

            # Update job status and summary in DB
            db.save_job(
                {
                    "id": job_id,
                    "completed_at": datetime.now(UTC).isoformat(),
                    "status": "completed",
                    "summary_valid": summary.get("valid", 0),
                    "summary_risky": summary.get("risky", 0),
                    "summary_invalid": summary.get("invalid", 0),
                    "avg_score": summary.get("avg_score", 0),
                    "top_risk_factors": summary.get("top_risk_factors", []),
                }
            )

            # Generate CSV output files for persistent downloads
            storage.generate_csv_outputs(job_id)

    threading.Thread(target=run, daemon=True).start()

    return jsonify({"job_id": job_id, "email_column": email_field})


@app.route("/progress")
def progress() -> Response:
    """Get current progress of a verification job."""
    job_id = request.args.get("job_id")

    # #region agent log
    import os, json
    with open(r'c:\Users\OxGh0\OneDrive\Desktop\Email Verifier Warp\Email Verifier Warp\.cursor\debug.log', 'a', encoding='utf-8') as f:
        f.write(json.dumps({"sessionId":"debug-session","runId":"pre-fix","hypothesisId":"H2","location":"app.py:1078","message":"progress endpoint called","data":{"job_id":job_id,"worker_pid":os.getpid(),"in_memory_jobs":list(data.keys())},"timestamp":int(__import__('time').time()*1000)})+'\n')
    # #endregion
    # #region agent log
    try:
        with open("/app/storage/debug.log", "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "sessionId": "debug-session",
                        "runId": "pre-fix",
                        "hypothesisId": "H2",
                        "location": "app.py:1088",
                        "message": "progress endpoint called (docker sink)",
                        "data": {
                            "job_id": job_id,
                            "worker_pid": os.getpid(),
                            "gunicorn_workers_env": os.environ.get("GUNICORN_WORKERS"),
                            "gunicorn_threads_env": os.environ.get("GUNICORN_THREADS"),
                            "gunicorn_timeout_env": os.environ.get("GUNICORN_TIMEOUT"),
                            "in_memory_jobs_count": len(data),
                        },
                        "timestamp": int(__import__("time").time() * 1000),
                    }
                )
                + "\n"
            )
    except Exception:
        pass
    # #endregion

    # Check in-memory first (for running jobs)
    with data_lock:
        d = data.get(job_id, {})
        # #region agent log
        import os, json
        with open(r'c:\Users\OxGh0\OneDrive\Desktop\Email Verifier Warp\Email Verifier Warp\.cursor\debug.log', 'a', encoding='utf-8') as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"pre-fix","hypothesisId":"H2","location":"app.py:1080","message":"in-memory lookup result","data":{"job_id":job_id,"found_in_memory":bool(d),"row":d.get("row",0) if d else 0,"progress":d.get("progress",0) if d else 0,"worker_pid":os.getpid()},"timestamp":int(__import__('time').time()*1000)})+'\n')
        # #endregion
        # #region agent log
        try:
            with open("/app/storage/debug.log", "a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "sessionId": "debug-session",
                            "runId": "pre-fix",
                            "hypothesisId": "H2",
                            "location": "app.py:1095",
                            "message": "in-memory lookup result (docker sink)",
                            "data": {
                                "job_id": job_id,
                                "found_in_memory": bool(d),
                                "row": (d.get("row", 0) if d else 0),
                                "progress": (d.get("progress", 0) if d else 0),
                                "worker_pid": os.getpid(),
                            },
                            "timestamp": int(__import__("time").time() * 1000),
                        }
                    )
                    + "\n"
                )
        except Exception:
            pass
        # #endregion
        if d:
            response_data = {
                "percent": d.get("progress", 0),
                "row": d.get("row", 0),
                "total": d.get("total", 0),
            }
            # Include summary when job is complete
            if d.get("progress", 0) >= 100 and d.get("summary"):
                response_data["summary"] = d["summary"]
            return jsonify(response_data)

    # Not in memory - check database for historical job
    job = db.get_job(job_id)
    if not job:
        return jsonify({"percent": 0, "row": 0, "total": 0, "error": "Job not found"})

    # Build response from DB job
    response_data = {
        "percent": 100 if job["status"] == "completed" else 0,
        "row": job.get("total_rows", 0) if job["status"] == "completed" else 0,
        "total": job.get("total_rows", 0),
        "status": job["status"],
    }

    # Include summary for completed jobs
    if job["status"] == "completed":
        response_data["summary"] = {
            "valid": job.get("summary_valid", 0),
            "risky": job.get("summary_risky", 0),
            "invalid": job.get("summary_invalid", 0),
            "avg_score": job.get("avg_score", 0),
            "top_risk_factors": job.get("top_risk_factors", []),
        }

    return jsonify(response_data)


@app.route("/log")
def log() -> Response:
    """Get the latest log message for a job."""
    job_id = request.args.get("job_id")
    with data_lock:
        return Response(data.get(job_id, {}).get("log", ""), mimetype="text/plain")


@app.route("/cancel", methods=["POST"])
@require_api_key
def cancel() -> tuple[str, int]:
    """Cancel a running verification job."""
    job_id = request.args.get("job_id")
    with data_lock:
        if job_id in data:
            data[job_id]["cancel"] = True
            # DB update happens in the run() thread when it detects cancel
    return "", 204


@app.route("/download")
def download() -> tuple[Response, int] | Response:
    """
    Download verified CSV with optional filtering.
    Filter types: all, valid, risky, risky_invalid, scores
    """
    job_id = request.args.get("job_id")
    filter_type = request.args.get("type", "all")

    # Try in-memory first (for running/recently completed jobs)
    with data_lock:
        job = data.get(job_id)
        if job:
            job["output"].seek(0)
            reader = list(csv.DictReader(job["output"]))
            filename = job["filename"]
            email_field = job.get("email_field", "email")
        else:
            reader = None
            filename = None
            email_field = "email"

    # Not in memory - try to load from disk storage
    if reader is None:
        csv_content = storage.get_csv_output(job_id, filter_type)
        if csv_content:
            # Get filename from DB
            db_job = db.get_job(job_id)
            filename = db_job.get("filename", "download.csv") if db_job else "download.csv"
            download_name = f"{filter_type}-verified-{filename}"
            return Response(
                csv_content,
                mimetype="text/csv",
                headers={"Content-Disposition": f"attachment; filename={download_name}"},
            )
        else:
            return jsonify({"error": "Invalid job ID"}), 404

    if not reader:
        return jsonify({"error": "No data available for download"}), 404

    # Filter based on type
    if filter_type == "valid":
        filtered = [row for row in reader if row.get("status") == "valid"]
    elif filter_type == "risky":
        filtered = [row for row in reader if row.get("status") == "risky"]
    elif filter_type == "risky_invalid":
        filtered = [row for row in reader if row.get("status") in ("risky", "invalid")]
    elif filter_type == "scores":
        # Scores-only export: email, status, reason, score, risk_factors
        filtered = []
        for row in reader:
            filtered.append(
                {
                    "email": row.get(email_field, ""),
                    "status": row.get("status", ""),
                    "reason": row.get("reason", ""),
                    "score": row.get("score", ""),
                    "risk_factors": row.get("risk_factors", ""),
                }
            )
    else:
        filtered = reader

    if not filtered:
        return jsonify({"error": f"No {filter_type} emails found"}), 404

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=filtered[0].keys())
    writer.writeheader()
    for row in filtered:
        writer.writerow(row)

    output.seek(0)
    download_name = f"{filter_type}-verified-{filename}"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={download_name}"},
    )


@app.route("/schema")
def schema() -> Response:
    """Return API schema and configuration information."""
    return jsonify(
        {
            "server_version": Config.VERSION,
            "validator_mode": Config.VALIDATOR_MODE,
            "scoring_version": Config.SCORING_VERSION,
            "download_types": ["all", "valid", "risky", "risky_invalid", "scores"],
            "supported_columns": ["email", "company", "website"],
            "max_upload_mb": Config.MAX_UPLOAD_MB,
            "max_csv_rows": Config.MAX_CSV_ROWS,
        }
    )


@app.route("/health")
def health() -> Response:
    """Health check endpoint."""
    return jsonify({"status": "ok"})


@app.get("/favicon.ico")
def favicon():
    """Return empty response to prevent 500 errors for favicon requests."""
    return ("", 204)


@app.route("/metrics")
def metrics() -> Response:
    """
    Simple metrics endpoint for monitoring.
    Returns JSON with job counts, storage stats, and configuration.
    """
    running_jobs = get_running_jobs_count()

    # Count completed jobs today
    from datetime import date

    today_start = date.today().isoformat()
    completed_today = db.count_jobs_since(today_start, status="completed")

    storage_stats = storage.get_storage_stats()

    return jsonify(
        {
            "status": "ok",
            "server_version": Config.VERSION,
            "timestamp": datetime.now(UTC).isoformat(),
            "validator_mode": Config.VALIDATOR_MODE,
            "jobs": {
                "running": running_jobs,
                "completed_today": completed_today,
                "max_concurrent": Config.MAX_CONCURRENT_JOBS,
                "total": storage_stats["job_count"],
            },
            "storage": {
                "db_path": Config.DB_PATH,
                "storage_dir": Config.STORAGE_DIR,
                "uploads_size_mb": round(storage_stats["uploads_size_bytes"] / 1024 / 1024, 2),
                "outputs_size_mb": round(storage_stats["outputs_size_bytes"] / 1024 / 1024, 2),
            },
            "config": {
                "max_upload_mb": Config.MAX_UPLOAD_MB,
                "max_csv_rows": Config.MAX_CSV_ROWS,
                "retention_days": Config.RETENTION_DAYS,
                "max_jobs": Config.MAX_JOBS,
                "stall_timeout_minutes": Config.JOB_STALL_TIMEOUT_MINUTES,
            },
        }
    )


# ============================================================================
# Job Management Endpoints (Persistence)
# ============================================================================


@app.route("/jobs")
def list_jobs() -> Response:
    """List all jobs with summaries, ordered by creation date descending."""
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))

    # Validate limits
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    jobs = db.list_jobs(limit, offset)
    total = db.get_job_count()

    return jsonify(
        {
            "jobs": jobs,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    )


@app.route("/jobs/<job_id>")
def get_job_detail(job_id: str) -> tuple[Response, int] | Response:
    """Get detailed information about a specific job."""
    job = db.get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    # Add available downloads
    job["downloads"] = ["all", "valid", "risky", "risky_invalid", "scores", "bundle"]

    return jsonify(job)


@app.route("/jobs/<job_id>", methods=["DELETE"])
@require_api_key
def delete_job_endpoint(job_id: str) -> tuple[Response, int] | tuple[str, int]:
    """Delete a job and all its associated files."""
    # Check if job exists
    job = db.get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    # Remove from in-memory if present
    with data_lock:
        if job_id in data:
            del data[job_id]

    # Delete from database (cascades to results)
    db.delete_job(job_id)

    # Delete files from storage
    storage.delete_job_files(job_id)

    logger.info("Job deleted", extra={"job_id": job_id})

    return "", 204


@app.route("/jobs/<job_id>/bundle")
def download_bundle(job_id: str) -> tuple[Response, int] | Response:
    """Download a ZIP bundle containing all CSVs and summary.json."""
    # Check if job exists and is completed
    job = db.get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    if job["status"] != "completed":
        return jsonify({"error": f"Job is not completed (status: {job['status']})"}), 400

    # Generate bundle
    bundle_path = storage.generate_bundle_zip(job_id)
    if not bundle_path:
        return jsonify({"error": "Failed to generate bundle"}), 500

    # Create download filename
    filename = job.get("filename", "export.csv")
    base_name = filename.rsplit(".", 1)[0] if "." in filename else filename
    download_name = f"{base_name}-bundle-{job_id[:8]}.zip"

    return send_file(
        bundle_path,
        as_attachment=True,
        download_name=download_name,
        mimetype="application/zip",
    )


# Helper for tests to clear in-memory data
def clear_memory_for_testing() -> None:
    """Clear in-memory job data. Only for testing purposes."""
    global data
    with data_lock:
        data.clear()


# Static file serving for frontend (used in Docker single-container deployment)
@app.route("/")
def serve_index() -> Response:
    """Serve the frontend index.html."""
    import os

    frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
    return send_from_directory(frontend_dir, "index.html")


@app.route("/<path:path>")
def serve_static(path: str) -> Response:
    """Serve static files from frontend directory."""
    import os

    frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
    return send_from_directory(frontend_dir, path)


if __name__ == "__main__":
    app.run(debug=Config.DEBUG, port=Config.PORT, host=Config.HOST)

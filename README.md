# Lead Validator - Email Verification Tool

![CI](https://github.com/YOUR_USERNAME/YOUR_REPO/workflows/CI/badge.svg)

A local email verification tool that validates emails via syntax checks, disposable/role-based detection, MX record lookup, and SMTP verification.

## Features

- **Drag-and-drop CSV upload** - Simply drop your CSV file to start verification
- **Real-time progress tracking** - Watch verification progress with live updates
- **Multiple concurrent jobs** - Verify multiple CSV files simultaneously
- **Job persistence** - Jobs survive page refresh AND backend restarts (stored in SQLite)
- **Cancel support** - Stop any job mid-run
- **Filtered downloads** - Download all, valid-only, risky-only, or risky+invalid results
- **Batch export** - Download all results as a ZIP bundle (5 CSVs + summary.json)
- **Job history** - View, manage, and re-download past verification jobs

## Verification Checks

Each email goes through the following validation:

1. **Syntax validation** - Valid email format
2. **Disposable domain check** - Detects temporary email services
3. **Role-based detection** - Identifies generic emails (info@, support@, etc.)
4. **MX record lookup** - Verifies domain has mail servers
5. **SMTP verification** - Confirms mailbox exists
6. **Catch-all detection** - Identifies domains that accept all emails

## Project Structure

```
Email Verifier Warp/
├── .github/
│   └── workflows/
│       └── ci.yml          # GitHub Actions CI pipeline
├── backend/
│   ├── app.py              # Flask API server
│   ├── config.py           # Centralized configuration
│   ├── db.py               # SQLite database operations
│   ├── storage.py          # File storage utilities
│   ├── Dockerfile          # Docker image definition
│   ├── pyproject.toml      # Black/Ruff/Mypy config
│   ├── requirements.txt    # Production dependencies
│   ├── requirements-dev.txt # Dev/test dependencies
│   ├── storage/            # Persistent storage directory
│   │   ├── lead_validator.db  # SQLite database
│   │   ├── uploads/        # Original uploaded CSVs
│   │   └── outputs/        # Generated CSV outputs
│   └── tests/              # Pytest test suite
├── frontend/
│   └── index.html          # Web UI
├── scripts/
│   └── smoke_test.py       # End-to-end smoke test
├── .pre-commit-config.yaml # Pre-commit hooks config
├── docker-compose.yml      # Docker orchestration
├── Fortune500leads.csv     # Sample data
├── README.md               # This file
└── .gitignore
```

## Prerequisites

- **Python 3.8+** (check with `python --version` or `python3 --version`)
- A modern web browser (Chrome, Firefox, Edge, Safari)
- **Docker** (optional, for containerized deployment)

## Quick Start with Docker (Recommended)

The easiest way to run the application:

```bash
# Build and start the application
docker compose up --build

# Access the application at http://localhost:5050
```

To stop:
```bash
docker compose down
```

### Docker Configuration

Copy `.env.example` to `.env` to customize:

```env
# Validator mode: 'real' for production, 'mock' for testing
VALIDATOR_MODE=real
```

### Running Tests in Docker

```bash
# Run the pytest test suite (uses mock mode automatically)
docker compose run -e VALIDATOR_MODE=mock backend pytest -v

# Run smoke test with sample data
docker compose run -e VALIDATOR_MODE=mock backend python scripts/smoke_test.py
```

### Windows

```powershell
# Navigate to the project folder
cd "C:\path\to\Email Verifier Warp\Email Verifier Warp"

# Create and activate virtual environment
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### Mac/Linux

```bash
# Navigate to the project folder
cd "/path/to/Email Verifier Warp/Email Verifier Warp"

# Create and activate virtual environment
cd backend
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Running the Application

You need **two terminal windows/tabs** - one for the backend and one for the frontend.

### Terminal 1: Start Backend Server

**Windows:**
```powershell
cd backend
.\venv\Scripts\Activate.ps1
python app.py
```

**Mac/Linux:**
```bash
cd backend
source venv/bin/activate
python3 app.py
```

You should see:
```
>>> LEAD VALIDATOR (mode=real) - Email Verification Service • Version 2.0.0 <<<
 * Running on http://0.0.0.0:5050
```

### Terminal 2: Start Frontend Server

**Both Windows and Mac/Linux:**
```bash
cd frontend
python -m http.server 3000
```

You should see:
```
Serving HTTP on :: port 3000 (http://[::]:3000/) ...
```

## Using the Tool

1. Open your browser and go to: **http://localhost:3000**
2. Drag a CSV file onto the drop zone (or click to browse)
3. Watch the progress bar as emails are verified
4. When complete, download your results using the provided links

## CSV File Requirements

Your CSV file must have:
- A column containing email addresses (auto-detected or specified)
- UTF-8 or Latin-1 encoding (UTF-8 BOM supported)
- CSV format with comma, semicolon, or tab delimiters (auto-detected)

### Supported Formats

**Standard CSV:**
```csv
name,email,company
John Doe,john@example.com,Acme Inc
Jane Smith,jane@example.org,Tech Corp
```

**Semicolon-delimited (European format):**
```csv
name;email;company
John Doe;john@example.com;Acme Inc
```

**Email formats in cells:**
```csv
name,email
Alice,"Alice Smith <alice@example.com>"
Bob,bob@example.com
```

The tool automatically:
- Detects the delimiter (comma, semicolon, or tab)
- Extracts emails from `Name <email@domain.com>` format
- Normalizes emails (lowercase domain, trim whitespace)
- Handles duplicate column names (`email`, `email_2`, etc.)

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/verify` | POST | Upload CSV and start verification job |
| `/progress?job_id=` | GET | Get current progress (percent, row, total, summary) |
| `/log?job_id=` | GET | Get latest log message |
| `/cancel?job_id=` | POST | Cancel a running job |
| `/download?job_id=&type=` | GET | Download results (all/valid/risky/risky_invalid/scores) |
| `/jobs?limit=&offset=` | GET | List all jobs (paginated, newest first) |
| `/jobs/<job_id>` | GET | Get detailed job info |
| `/jobs/<job_id>` | DELETE | Delete job and all associated files |
| `/jobs/<job_id>/bundle` | GET | Download ZIP bundle (all CSVs + summary.json) |
| `/schema` | GET | Get API schema, scoring version, supported types |
| `/health` | GET | Health check endpoint |
| `/metrics` | GET | Get monitoring metrics (running jobs, storage stats) |

### POST /verify Options

| Field | Type | Description |
|-------|------|-------------|
| `file` | File | Required. CSV file to verify |
| `email_column` | String | Optional. Specify which column contains emails |
| `job_name` | String | Optional. Custom name for the job |
| `delimiter` | String | Optional. CSV delimiter (comma/semicolon/tab). Auto-detected if not provided |

If `email_column` is not provided, the API auto-detects email columns. If multiple candidates are found, it returns a 400 error with `email_column_candidates` for the client to choose from.

### Concurrency Limits

The API limits concurrent jobs to prevent resource exhaustion:
- **Default**: 3 concurrent jobs (`MAX_CONCURRENT_JOBS`)
- **When exceeded**: Returns HTTP 429 with a friendly message
- **UI behavior**: Shows a banner asking user to wait

## Verification Results

Each email is classified as:

| Status | Description |
|--------|-------------|
| `valid` | Email passed all checks (SMTP confirmed) |
| `risky` | Email might exist but couldn't be confirmed (timeout, soft fail, catch-all) |
| `invalid` | Email definitely doesn't exist or is problematic |

Reasons include:
- `smtp_ok` - Valid email confirmed via SMTP
- `smtp_timeout` - Could not connect to mail server
- `smtp_reject` - Mailbox does not exist
- `domain_accepts_all` - Catch-all domain (can't verify specific mailbox)
- `no_mx` - Domain has no mail servers
- `bad_syntax` - Invalid email format
- `disposable_domain` - Temporary email service
- `role_based` - Generic email (info@, support@, etc.)
- `empty_email` - No email provided

## Confidence Scoring

Each verified email receives a **confidence score** (0-100) and a list of **risk factors**.

### Score Calculation

| Condition | Score Impact | Risk Factor |
|-----------|--------------|-------------|
| Valid SMTP confirmed | 100 (base) | - |
| Free email provider (gmail, yahoo) | -5 | `free_email_provider` |
| Catch-all domain | -15 | `catch_all_domain` |
| Role-based email (info@, support@) | -25 | `role_based_email` |
| SMTP timeout/soft fail | -25 | `smtp_unreachable` |
| Unverifiable domain | -40 | `unverifiable_domain` |
| Invalid syntax | 0 | `invalid_syntax` |
| Disposable provider | 0 | `disposable_provider` |
| No mail server | 0 | `no_mail_server` |
| Mailbox not found | 0 | `mailbox_not_found` |

### Score Interpretation

| Score Range | Meaning |
|-------------|---------|
| 90-100 | High confidence - Safe to email |
| 70-89 | Medium confidence - Proceed with caution |
| 40-69 | Low confidence - Consider removing |
| 0-39 | Very low - Do not email |

### Download Types

| Type | Description |
|------|-------------|
| `all` | All leads with full data + status + score |
| `valid` | Only emails with status "valid" |
| `risky` | Only emails with status "risky" |
| `risky_invalid` | Emails with status "risky" or "invalid" |
| `scores` | Compact format: email, status, reason, score, risk_factors only |
| `bundle` | ZIP file containing all 5 CSVs + summary.json (via `/jobs/<job_id>/bundle`) |

## Smart Column Detection

The tool automatically detects email columns from your CSV headers:

**Recognized patterns:**
- Exact: `email`, `e-mail`, `e_mail`, `emailaddress`, `email_address`
- Contains: any column with "email" or "mail" in the name

**Behavior:**
- **Single match**: Automatically uses that column
- **Multiple matches**: Shows a picker dialog to choose
- **No match**: Shows error with available columns

You can also specify `email_column` explicitly in the API request to bypass auto-detection.

## Troubleshooting

### "No 'email' column found"
Your CSV must have a column named exactly `email` (case-insensitive). Check your CSV headers.

### "Failed to upload file. Is the backend running?"
Make sure the backend server is running in Terminal 1.

### Jobs not resuming after refresh
Jobs are now stored in SQLite and persist across backend restarts. The UI will automatically show job history from the database.

### Slow verification
SMTP checks can take 10+ seconds per email, especially for slow or rate-limiting mail servers.

### CORS errors in browser console
Make sure you're accessing the frontend via `http://localhost:3000`, not by opening the file directly.

## Configuration

### API URL Detection

The frontend automatically detects the API URL:
- When served from `localhost:3000` (dev mode) → uses `http://localhost:5050`
- When served from the backend (Docker/production) → uses same origin

### Changing the Backend Port

Edit `backend/app.py` and find this line at the bottom:
```python
app.run(debug=True, port=5050, host='0.0.0.0')
```

For Docker, also update `docker-compose.yml`:
```yaml
ports:
  - "5050:5050"  # Change both numbers
```

## Development

### Mock Mode

The application supports two validator modes:

- **`VALIDATOR_MODE=real`** (default): Full email verification with DNS/MX/SMTP checks
- **`VALIDATOR_MODE=mock`**: Deterministic verification for testing (no network calls)

Mock mode rules:
- `example.com`, `example.org`, `test.com` domains → valid
- `.edu`, `.gov` domains → valid
- Disposable domains (mailinator.com, etc.) → invalid
- Role-based emails (info@, support@, etc.) → invalid
- All other domains → risky

### Running Tests Locally

```bash
cd backend
source venv/bin/activate  # or .\venv\Scripts\Activate.ps1 on Windows

# Install dev dependencies
pip install -r requirements-dev.txt

# Run tests (automatically uses mock mode)
pytest -v

# Run specific test file
pytest tests/test_health.py -v
```

### Smoke Testing

```bash
# With Docker (recommended)
docker compose up -d
docker compose run -e VALIDATOR_MODE=mock backend python scripts/smoke_test.py
docker compose down

# Locally (set mock mode for fast testing)
set VALIDATOR_MODE=mock  # Windows
export VALIDATOR_MODE=mock  # Mac/Linux
python scripts/smoke_test.py
```

## Development Quality Tools

### Code Formatting & Linting

```bash
cd backend

# Format code with black
black .

# Lint with ruff
ruff check .
ruff check --fix .  # Auto-fix issues

# Type check with mypy
mypy . --ignore-missing-imports
```

### Pre-commit Hooks

Install pre-commit hooks to automatically check code quality before commits:

```bash
# Install pre-commit (one-time setup)
pip install pre-commit

# Install git hooks
pre-commit install

# Run manually on all files
pre-commit run --all-files
```

The hooks will automatically run on `git commit` and prevent commits that don't meet quality standards.

## Configuration Reference

All configuration is done via environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `PORT` | `5050` | Backend server port |
| `HOST` | `0.0.0.0` | Backend server host |
| `VALIDATOR_MODE` | `real` | Email validation mode: `real` (SMTP/DNS) or `mock` (deterministic testing) |
| `MAX_UPLOAD_MB` | `25` | Maximum CSV upload size in megabytes (1-100) |
| `MAX_CSV_ROWS` | `10000` | Maximum number of rows in CSV |
| `MAX_LINE_LENGTH` | `10000` | Maximum characters per CSV line |
| `CORS_ORIGINS` | `` (empty) | Comma-separated allowed origins. Empty = localhost only (secure default) |
| `LOG_LEVEL` | `INFO` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `FLASK_ENV` | `development` | Flask environment mode |
| `STORAGE_DIR` | `backend/storage` | Directory for persistent storage (DB + files) |
| `DB_PATH` | `backend/storage/lead_validator.db` | Path to SQLite database |
| `RETENTION_DAYS` | `14` | Auto-delete jobs older than this many days |
| `MAX_JOBS` | `200` | Maximum number of jobs to retain (oldest deleted first) |
| `MAX_CONCURRENT_JOBS` | `3` | Maximum simultaneous verification jobs (1-20) |
| `JOB_STALL_TIMEOUT_MINUTES` | `10` | Mark jobs as failed if no activity for this long |
| `JOB_HEARTBEAT_INTERVAL_ROWS` | `10` | Update heartbeat every N rows processed |

### Examples

```bash
# Development with permissive CORS
export CORS_ORIGINS="http://localhost:3000,http://localhost:8080"

# Production with strict limits
export MAX_UPLOAD_MB=10
export LOG_LEVEL=WARNING
export VALIDATOR_MODE=real

# Testing
export VALIDATOR_MODE=mock
export LOG_LEVEL=DEBUG
```

## Security Notes

### Upload Limits

- Maximum file size: 25MB by default (configurable via `MAX_UPLOAD_MB`)
- Maximum CSV rows: 10,000 rows (configurable via `MAX_CSV_ROWS`)
- Maximum line length: 10,000 characters
- Files exceeding limits are rejected with clear error messages

### CORS Policy

- **Default**: Localhost origins only (`localhost:3000`, `localhost:5050`)
- **Custom**: Set `CORS_ORIGINS` environment variable to allow specific origins
- **Never use wildcard** (`*`) in production

Example for local development:
```bash
export CORS_ORIGINS="http://localhost:3000"
```

### Request Tracking

Every request receives a unique `X-Request-ID` header for tracing and debugging. Clients can provide their own request ID via the `X-Request-ID` request header.

### Error Handling

- Exceptions are logged with full stack traces
- API responses never expose internal error details
- All errors return safe JSON: `{"error": "description"}`

## CI/CD

GitHub Actions runs on every push and pull request:

- **Tests**: Runs pytest in mock mode on Ubuntu and Windows
- **Lint**: Checks formatting with black, linting with ruff, types with mypy
- **Smoke Test**: Runs end-to-end smoke test

All checks must pass before merging.

## Job Persistence

Jobs are now stored in a SQLite database (`backend/storage/lead_validator.db`) for persistence:

### Features
- **Survives restarts**: Jobs persist across backend restarts
- **Full history**: View and manage all past verification jobs
- **Batch export**: Download all results as a ZIP bundle
- **Auto-cleanup**: Old jobs are automatically removed based on retention settings

### Storage Structure
```
backend/storage/
├── lead_validator.db    # SQLite database (jobs + results)
├── uploads/             # Original uploaded CSV files
│   └── {job_id}.csv
└── outputs/             # Generated download files
    └── {job_id}/
        ├── all.csv
        ├── valid.csv
        ├── risky.csv
        ├── risky_invalid.csv
        ├── scores.csv
        └── bundle.zip
```

### Retention Settings
- `RETENTION_DAYS=14`: Jobs older than 14 days are auto-deleted on startup
- `MAX_JOBS=200`: Only the 200 most recent jobs are kept

### Job Management API
- `GET /jobs`: List all jobs with pagination
- `GET /jobs/<id>`: Get detailed job info
- `DELETE /jobs/<id>`: Delete job and all files
- `GET /jobs/<id>/bundle`: Download ZIP bundle

## Monitoring & Observability

### Metrics Endpoint

The `/metrics` endpoint provides operational insights:

```json
{
  "status": "ok",
  "timestamp": "2024-01-15T10:30:00Z",
  "validator_mode": "mock",
  "jobs": {
    "running": 1,
    "completed_today": 15,
    "max_concurrent": 3,
    "total": 127
  },
  "storage": {
    "db_path": "/app/storage/lead_validator.db",
    "storage_dir": "/app/storage",
    "uploads_size_mb": 12.5,
    "outputs_size_mb": 45.2
  },
  "config": {
    "max_upload_mb": 25,
    "max_csv_rows": 10000,
    "retention_days": 14,
    "stall_timeout_minutes": 10
  }
}
```

### Job Health Monitoring

Jobs include heartbeat tracking to detect stalled processes:
- **Heartbeat**: Updated every N rows (default: 10)
- **Stall detection**: Background thread checks for inactive jobs
- **Auto-recovery**: Stalled jobs marked as "failed" with error message
- **Timeout**: Configurable via `JOB_STALL_TIMEOUT_MINUTES`

### Structured Logging

All backend logs use structured key=value format:
```
timestamp="2024-01-15T10:30:00Z" level=INFO message="Job created" job_id="abc123" file_name="leads.csv" row_count=500
```

Request IDs (`X-Request-ID` header) are included for tracing.

## Release Checklist

Before cutting a new release:

### 1. Version Bump
- Update `VERSION` file with new version number (e.g., `2.1.0`)
- Update `backend/config.py` `VERSION` constant
- Update `CHANGELOG.md` with release notes
- Update `backend/db.py` `SCHEMA_VERSION` if schema changed

### 2. Quality Gates

```bash
cd backend

# Format check
black --check .

# Linting
ruff check .

# Type checking
mypy . --ignore-missing-imports

# Pre-commit (run all hooks)
pre-commit run --all-files
```

### 3. Test Suite

```bash
# Run all tests (uses mock mode automatically)
cd backend
pytest -v

# Run smoke test
cd ..
python scripts/smoke_test.py
```

### 4. Docker Build

```bash
docker compose build
docker compose up -d
# Test application manually
docker compose down
```

### 5. Documentation
- Ensure README is up to date
- Update API endpoint table if changed
- Update configuration reference if new env vars added

### 6. Tag and Release

```bash
# Commit version changes
git add VERSION CHANGELOG.md backend/config.py backend/db.py
git commit -m "Release v2.0.0"

# Create annotated tag
git tag -a v2.0.0 -m "Phase 2F: Release-grade polish"

# Push tag
git push origin v2.0.0
git push origin main
```

## Upgrade Notes

### Upgrading to 2.0.0

**Database Migration:**
- Schema automatically migrates on first startup
- `schema_version` table tracks migration state
- No manual intervention needed for minor schema changes

**Configuration:**
- No breaking changes
- New `TESTING` env var controls background thread behavior

**API Changes:**
- Error responses now include structured envelope (backward compatible):
  ```json
  {
    "error": {
      "code": "TOO_MANY_CONCURRENT_JOBS",
      "message": "Maximum 3 concurrent jobs allowed...",
      "details": { "running_jobs": 3, "max_allowed": 3 }
    },
    "request_id": "abc-123-def"
  }
  ```
- `/schema` and `/metrics` now include `server_version` field

### Manual Migration (if needed)

If automatic migration fails, run these SQL statements:

```sql
-- Add last_heartbeat column (if missing)
ALTER TABLE jobs ADD COLUMN last_heartbeat TEXT;

-- Add schema_version table
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

INSERT INTO schema_version (version, applied_at) VALUES (2, datetime('now'));
```

### Downgrading

Downgrading is not automatically supported. To downgrade:
1. Back up the `storage/` directory
2. Install older version
3. If schema is incompatible, delete `lead_validator.db` (data loss)

## What's Next

Future improvements planned:
- WebSocket for real-time updates (replace polling)
- React + TypeScript modern frontend
- Rate limiting and retry logic
- API authentication
- Advanced filtering (by score, date range, risk factors)
- Webhook notifications on job completion
- Bulk operations (verify multiple files in one request)
- Integration with external enrichment services

## License

For internal/personal use.

---

Made with love for lead generation

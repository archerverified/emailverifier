# Changelog

All notable changes to the Lead Validator project are documented in this file.

## [2.0.0] - 2026-01-13 - Phase 2F Release

### Added
- Structured error responses with error codes and request IDs
- Server version in `/schema` and `/metrics` endpoints
- Database schema versioning with automatic migrations
- JobMonitor class with clean lifecycle management (no more background thread warnings)
- Comprehensive stall detection tests with time provider injection
- Release checklist and upgrade notes in README
- VERSION file for easy version tracking
- CHANGELOG.md for release notes

### Changed
- Background stall detection refactored into JobMonitor class
- Stall detection disabled in TESTING mode
- Improved error handling with consistent envelope format
- Rate-limited stall detection warnings

### Fixed
- Background thread warnings during pytest teardown
- FileNotFoundError when monitor accesses cleaned-up temp directories

## [1.5.0] - 2026-01-13 - Phase 2E

### Added
- CSV delimiter auto-detection (comma, semicolon, tab)
- Email extraction from "Name <email@domain.com>" format
- Email normalization (lowercase domain, trim whitespace)
- Concurrency limits (MAX_CONCURRENT_JOBS) with 429 responses
- Job health monitoring with heartbeat tracking
- `/metrics` endpoint for monitoring
- 34 new edge case tests

### Changed
- CSV ingestion now handles BOM, duplicate headers, quoted fields
- Storage operations hardened against path traversal
- Output generation made idempotent

## [1.0.0] - 2026-01-12 - Phase 2D

### Added
- SQLite persistence for jobs and results
- Job history with list/view/delete operations
- Batch export (ZIP bundles with all CSVs + summary.json)
- Automatic job retention and cleanup
- `/jobs` endpoint for listing jobs
- `/jobs/<id>/bundle` endpoint for ZIP downloads

## [0.9.0] - 2026-01-11 - Phase 2C

### Added
- Email confidence scoring (0-100)
- Risk factor analysis per email
- Smart CSV column detection
- Column picker UI for ambiguous CSVs
- `/download?type=scores` for scores-only export
- `/schema` endpoint for API information

## [0.8.0] - 2026-01-10 - Phase 2B

### Added
- CI/CD with GitHub Actions
- Code quality tools (black, ruff, mypy)
- Pre-commit hooks
- Structured logging with request IDs
- Upload size limits
- Restrictive CORS by default
- Configuration validation

## [0.7.0] - 2026-01-09 - Phase 2A

### Added
- Docker and docker-compose support
- Automated test suite (pytest)
- Mock mode for testing (VALIDATOR_MODE=mock)
- Smoke test script
- Health check endpoint

## [0.1.0] - 2026-01-08 - Phase 1

### Added
- Initial prototype with basic email verification
- CSV upload and processing
- Progress tracking with polling
- Filtered downloads (all/valid/risky/risky_invalid)
- Job persistence in localStorage
- Cancel functionality

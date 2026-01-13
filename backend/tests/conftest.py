"""
Pytest configuration and fixtures for Lead Validator tests.
"""

import os
import shutil
import sys
import tempfile

import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Force mock mode for all tests - must be set before importing app
os.environ["VALIDATOR_MODE"] = "mock"

# Enable testing mode to disable background threads (like JobMonitor)
os.environ["TESTING"] = "1"

# Create a temporary directory for test storage
_test_temp_dir = tempfile.mkdtemp(prefix="lead_validator_test_")
os.environ["STORAGE_DIR"] = _test_temp_dir
os.environ["DB_PATH"] = os.path.join(_test_temp_dir, "test.db")

# Import config first to apply the settings
import config  # noqa: E402

# Force reload config values after setting env vars
config.Config.STORAGE_DIR = _test_temp_dir
config.Config.DB_PATH = os.path.join(_test_temp_dir, "test.db")

import db  # noqa: E402
import storage  # noqa: E402
from app import app as flask_app  # noqa: E402


def pytest_configure(config):
    """Ensure storage is set up before tests."""
    storage.ensure_storage_dirs()
    db.init_db()


def pytest_unconfigure(config):
    """Clean up temporary directory and stop any background services."""
    # Ensure job monitor is stopped before cleanup (prevents file access errors)
    try:
        import job_monitor

        job_monitor.stop_monitor()
    except Exception:
        pass

    global _test_temp_dir
    if _test_temp_dir and os.path.exists(_test_temp_dir):
        shutil.rmtree(_test_temp_dir, ignore_errors=True)


@pytest.fixture(autouse=True)
def reset_db_and_storage():
    """Reset database and storage before each test."""
    # Clear in-memory data
    from app import clear_memory_for_testing

    clear_memory_for_testing()

    # Clear database tables
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM job_results")
        conn.execute("DELETE FROM jobs")
        conn.commit()
    finally:
        conn.close()

    # Clear storage files (except .gitkeep)
    uploads_dir = os.path.join(config.Config.STORAGE_DIR, "uploads")
    outputs_dir = os.path.join(config.Config.STORAGE_DIR, "outputs")

    for directory in [uploads_dir, outputs_dir]:
        if os.path.exists(directory):
            for item in os.listdir(directory):
                if item == ".gitkeep":
                    continue
                path = os.path.join(directory, item)
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    os.remove(path)

    yield


@pytest.fixture
def app():
    """Create application for testing."""
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()

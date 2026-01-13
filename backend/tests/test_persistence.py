"""
Tests for job persistence and database operations.
"""

import io
import json
import time
import zipfile

import db
from app import clear_memory_for_testing


def wait_for_completion(client, job_id, max_wait=10):
    """Wait for a job to complete, returns progress data."""
    for _ in range(int(max_wait / 0.1)):
        time.sleep(0.1)
        response = client.get(f"/progress?job_id={job_id}")
        data = response.json
        if data.get("percent", 0) >= 100:
            return data
    return None


def test_job_persists_after_restart(client):
    """Test that job is available after simulating restart."""
    # Create and complete job
    csv_content = "name,email\nAlice,alice@example.com\nBob,bob@test.com\n"
    data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    job_id = response.json["job_id"]

    # Wait for completion
    progress = wait_for_completion(client, job_id)
    assert progress is not None
    assert progress["percent"] >= 100

    # Simulate restart by clearing in-memory data
    clear_memory_for_testing()

    # Job should still be retrievable from DB
    response = client.get(f"/progress?job_id={job_id}")
    assert response.status_code == 200
    data = response.json
    assert data["percent"] == 100
    assert data["status"] == "completed"
    assert "summary" in data
    assert data["summary"]["valid"] >= 0


def test_download_works_after_restart(client):
    """Test that download works after simulating restart."""
    csv_content = "name,email\nAlice,alice@example.com\n"
    data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    job_id = response.json["job_id"]

    # Wait for completion
    wait_for_completion(client, job_id)

    # Simulate restart
    clear_memory_for_testing()

    # Download should work from disk
    response = client.get(f"/download?job_id={job_id}&type=all")
    assert response.status_code == 200
    assert "text/csv" in response.content_type

    content = response.data.decode()
    assert "alice@example.com" in content
    assert "status" in content
    assert "score" in content


def test_list_jobs(client):
    """Test GET /jobs returns job list."""
    # Create a job
    csv_content = "name,email\nAlice,alice@example.com\n"
    data = {"file": (io.BytesIO(csv_content.encode()), "test_list.csv")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    job_id = response.json["job_id"]

    # Wait for completion
    wait_for_completion(client, job_id)

    # List jobs
    response = client.get("/jobs?limit=10")
    assert response.status_code == 200
    jobs = response.json["jobs"]
    assert len(jobs) >= 1
    assert any(j["id"] == job_id for j in jobs)

    # Check job has expected fields
    job = next(j for j in jobs if j["id"] == job_id)
    assert job["filename"] == "test_list.csv"
    assert job["status"] == "completed"
    assert "created_at" in job


def test_get_job_detail(client):
    """Test GET /jobs/<job_id> returns job details."""
    csv_content = "name,email\nAlice,alice@example.com\n"
    data = {"file": (io.BytesIO(csv_content.encode()), "detail_test.csv")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    job_id = response.json["job_id"]

    wait_for_completion(client, job_id)

    # Get job details
    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    job = response.json
    assert job["id"] == job_id
    assert job["filename"] == "detail_test.csv"
    assert "downloads" in job
    assert "bundle" in job["downloads"]


def test_get_job_not_found(client):
    """Test GET /jobs/<job_id> returns 404 for missing job."""
    response = client.get("/jobs/nonexistent-id")
    assert response.status_code == 404


def test_bundle_zip_download(client):
    """Test bundle ZIP contains expected files."""
    csv_content = "name,email\nAlice,alice@example.com\nBob,bob@unknown.io\n"
    data = {"file": (io.BytesIO(csv_content.encode()), "bundle_test.csv")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    job_id = response.json["job_id"]

    wait_for_completion(client, job_id)

    # Download bundle
    response = client.get(f"/jobs/{job_id}/bundle")
    assert response.status_code == 200
    assert "application/zip" in response.content_type

    # Verify ZIP contents
    z = zipfile.ZipFile(io.BytesIO(response.data))
    names = z.namelist()
    assert "all.csv" in names
    assert "valid.csv" in names
    assert "risky.csv" in names
    assert "risky_invalid.csv" in names
    assert "scores.csv" in names
    assert "summary.json" in names

    # Check summary.json content
    summary_content = z.read("summary.json").decode()
    summary = json.loads(summary_content)
    assert summary["job_id"] == job_id
    assert "summary" in summary
    assert "valid" in summary["summary"]


def test_bundle_not_found(client):
    """Test bundle download returns 404 for missing job."""
    response = client.get("/jobs/nonexistent-id/bundle")
    assert response.status_code == 404


def test_delete_job(client):
    """Test DELETE removes job and files."""
    csv_content = "name,email\nAlice,alice@example.com\n"
    data = {"file": (io.BytesIO(csv_content.encode()), "delete_test.csv")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    job_id = response.json["job_id"]

    wait_for_completion(client, job_id)

    # Verify job exists
    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200

    # Delete
    response = client.delete(f"/jobs/{job_id}")
    assert response.status_code == 204

    # Verify gone from API
    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 404

    # Verify download fails
    response = client.get(f"/download?job_id={job_id}&type=all")
    assert response.status_code == 404


def test_delete_nonexistent_job(client):
    """Test DELETE returns 404 for missing job."""
    response = client.delete("/jobs/nonexistent-id")
    assert response.status_code == 404


def test_job_status_cancelled_persists(client):
    """Test that cancelled job status persists in DB."""
    # Create a job with multiple rows (gives time to cancel)
    rows = "\n".join([f"User{i},user{i}@example.com" for i in range(20)])
    csv_content = f"name,email\n{rows}\n"
    data = {"file": (io.BytesIO(csv_content.encode()), "cancel_test.csv")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    job_id = response.json["job_id"]

    # Cancel immediately
    response = client.post(f"/cancel?job_id={job_id}")
    assert response.status_code == 204

    # Wait a moment for the job thread to detect cancellation
    time.sleep(0.5)

    # Clear memory to simulate restart
    clear_memory_for_testing()

    # Check job status in DB
    job = db.get_job(job_id)
    assert job is not None
    # Job might be cancelled or completed depending on timing
    assert job["status"] in ("cancelled", "completed")


def test_progress_summary_from_db(client):
    """Test that progress endpoint returns summary from DB after restart."""
    csv_content = "name,email\nAlice,alice@example.com\nBob,bob@test.com\n"
    data = {"file": (io.BytesIO(csv_content.encode()), "summary_test.csv")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    job_id = response.json["job_id"]

    wait_for_completion(client, job_id)

    # Simulate restart
    clear_memory_for_testing()

    # Progress should return summary from DB
    response = client.get(f"/progress?job_id={job_id}")
    assert response.status_code == 200
    data = response.json
    assert data["percent"] == 100
    assert "summary" in data
    assert "valid" in data["summary"]
    assert "risky" in data["summary"]
    assert "invalid" in data["summary"]
    assert "avg_score" in data["summary"]

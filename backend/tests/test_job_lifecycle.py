"""
Tests for complete job lifecycle: create, poll, download, cancel.
"""

import io
import time


def test_job_lifecycle(client):
    """Test complete job lifecycle: create, poll, download."""
    # Create job with small CSV
    csv_content = "name,email\nAlice,alice@example.com\nBob,bob@test.io\n"
    data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    job_id = response.json["job_id"]

    # Poll progress until complete (mock mode is fast)
    max_attempts = 50
    progress = None
    for _ in range(max_attempts):
        response = client.get(f"/progress?job_id={job_id}")
        assert response.status_code == 200
        progress = response.json
        assert "percent" in progress
        assert "total" in progress
        assert "row" in progress
        if progress["percent"] >= 100:
            break
        time.sleep(0.05)

    assert progress is not None
    assert progress["percent"] == 100
    assert progress["total"] == 2

    # Download results
    response = client.get(f"/download?job_id={job_id}&type=all")
    assert response.status_code == 200
    assert "text/csv" in response.content_type

    # Verify CSV has original columns + status + reason + score + risk_factors
    csv_text = response.data.decode("utf-8")
    lines = csv_text.strip().replace("\r", "").split("\n")
    headers = [h.strip() for h in lines[0].split(",")]
    assert "name" in headers
    assert "email" in headers
    assert "status" in headers
    assert "reason" in headers
    assert "score" in headers
    assert "risk_factors" in headers

    # Verify data rows exist
    assert len(lines) >= 3  # header + 2 data rows


def test_download_filtered_results(client):
    """Test downloading filtered results (valid, risky, etc.)."""
    # Create job with emails that will have different statuses in mock mode
    # example.com -> valid, other domains -> risky
    csv_content = "name,email\nValid,valid@example.com\nRisky,risky@unknown.io\n"
    data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")
    job_id = response.json["job_id"]

    # Wait for completion
    for _ in range(50):
        response = client.get(f"/progress?job_id={job_id}")
        if response.json["percent"] >= 100:
            break
        time.sleep(0.05)

    # Test valid filter
    response = client.get(f"/download?job_id={job_id}&type=valid")
    assert response.status_code == 200
    csv_text = response.data.decode("utf-8")
    assert "valid@example.com" in csv_text

    # Test risky filter
    response = client.get(f"/download?job_id={job_id}&type=risky")
    assert response.status_code == 200
    csv_text = response.data.decode("utf-8")
    assert "risky@unknown.io" in csv_text


def test_log_endpoint(client):
    """Test that log endpoint returns current verification status."""
    # Create job
    csv_content = "name,email\nTest,test@example.com\n"
    data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")
    job_id = response.json["job_id"]

    # Wait a moment then check log
    time.sleep(0.2)
    response = client.get(f"/log?job_id={job_id}")
    assert response.status_code == 200
    assert response.content_type == "text/plain; charset=utf-8"


def test_cancel_job(client):
    """Test that cancel stops a running job."""
    # Create job with larger CSV to ensure it has time to run
    rows = "\n".join([f"User{i},user{i}@test.com" for i in range(100)])
    csv_content = f"name,email\n{rows}"
    data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")
    job_id = response.json["job_id"]

    # Cancel the job immediately
    response = client.post(f"/cancel?job_id={job_id}")
    assert response.status_code == 204

    # Verify we can still get progress (doesn't error)
    time.sleep(0.1)
    response = client.get(f"/progress?job_id={job_id}")
    assert response.status_code == 200
    assert "percent" in response.json


def test_invalid_job_id(client):
    """Test that invalid job ID returns 404."""
    response = client.get("/download?job_id=invalid-uuid&type=all")
    assert response.status_code == 404
    assert "error" in response.json


def test_progress_unknown_job(client):
    """Test that progress for unknown job returns zeros."""
    response = client.get("/progress?job_id=unknown-job-id")
    assert response.status_code == 200
    progress = response.json
    assert progress["percent"] == 0
    assert progress["total"] == 0
    assert progress["row"] == 0

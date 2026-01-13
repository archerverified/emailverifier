"""
Tests for email scoring and column detection functionality.
"""

import io
import time


def test_scoring_mock_valid(client):
    """Test that valid emails in mock mode get high scores."""
    csv_content = "name,email\nAlice,alice@example.com\n"
    data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    job_id = response.json["job_id"]

    # Wait for completion
    for _ in range(50):
        time.sleep(0.1)
        progress = client.get(f"/progress?job_id={job_id}").json
        if progress["percent"] >= 100:
            break

    # Download and check score
    response = client.get(f"/download?job_id={job_id}&type=all")
    assert response.status_code == 200
    content = response.data.decode()
    lines = content.strip().split("\n")
    assert len(lines) == 2  # header + 1 row

    # Check headers include score and risk_factors
    headers = [h.strip() for h in lines[0].split(",")]
    assert "score" in headers
    assert "risk_factors" in headers

    # Check score is high for valid email
    score_idx = headers.index("score")
    values = lines[1].split(",")
    score = int(values[score_idx])
    assert score >= 90, f"Expected high score for valid email, got {score}"


def test_scoring_mock_risky(client):
    """Test that risky emails in mock mode get medium scores."""
    csv_content = "name,email\nBob,bob@unknown-domain-xyz.io\n"
    data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    job_id = response.json["job_id"]

    # Wait for completion
    for _ in range(50):
        time.sleep(0.1)
        progress = client.get(f"/progress?job_id={job_id}").json
        if progress["percent"] >= 100:
            break

    # Download and check score
    response = client.get(f"/download?job_id={job_id}&type=all")
    content = response.data.decode()
    lines = content.strip().split("\n")
    headers = [h.strip() for h in lines[0].split(",")]

    score_idx = headers.index("score")
    risk_factors_idx = headers.index("risk_factors")

    values = lines[1].split(",")
    score = int(values[score_idx])
    risk_factors = values[risk_factors_idx]

    assert 40 <= score <= 80, f"Expected medium score for risky email, got {score}"
    assert "unverifiable_domain" in risk_factors


def test_scoring_mock_invalid(client):
    """Test that invalid emails get score of 0."""
    csv_content = "name,email\nBad,not-an-email\n"
    data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    job_id = response.json["job_id"]

    # Wait for completion
    for _ in range(50):
        time.sleep(0.1)
        progress = client.get(f"/progress?job_id={job_id}").json
        if progress["percent"] >= 100:
            break

    # Download and check score
    response = client.get(f"/download?job_id={job_id}&type=all")
    content = response.data.decode()
    lines = content.strip().split("\n")
    headers = [h.strip() for h in lines[0].split(",")]

    score_idx = headers.index("score")
    values = lines[1].split(",")
    score = int(values[score_idx])

    assert score == 0, f"Expected score 0 for invalid email, got {score}"


def test_scoring_role_based(client):
    """Test that role-based emails get penalty but are risky, not invalid."""
    csv_content = "name,email\nSupport,support@example.com\n"
    data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    job_id = response.json["job_id"]

    # Wait for completion
    for _ in range(50):
        time.sleep(0.1)
        progress = client.get(f"/progress?job_id={job_id}").json
        if progress["percent"] >= 100:
            break

    # Download and check
    response = client.get(f"/download?job_id={job_id}&type=all")
    content = response.data.decode()
    lines = content.strip().split("\n")
    headers = [h.strip() for h in lines[0].split(",")]

    status_idx = headers.index("status")
    score_idx = headers.index("score")
    risk_factors_idx = headers.index("risk_factors")

    values = lines[1].split(",")
    status = values[status_idx]
    score = int(values[score_idx])
    risk_factors = values[risk_factors_idx]

    assert status == "risky"
    assert 70 <= score <= 80, f"Expected score around 75 for role-based, got {score}"
    assert "role_based" in risk_factors


def test_column_detection_single(client):
    """Test auto-detection when single email column exists."""
    csv_content = "name,email,company\nAlice,alice@example.com,Acme\n"
    data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")

    # Should succeed with auto-detection
    assert response.status_code == 200
    assert "job_id" in response.json
    assert response.json.get("email_column") == "email"


def test_column_detection_email_address(client):
    """Test auto-detection of 'Email Address' column."""
    csv_content = "name,Email Address,company\nAlice,alice@example.com,Acme\n"
    data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")

    assert response.status_code == 200
    assert response.json.get("email_column") == "Email Address"


def test_column_detection_multiple_candidates(client):
    """Test that multiple email columns returns candidates list."""
    csv_content = "name,email,contact_email\nAlice,alice@example.com,alice2@test.com\n"
    data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")

    # Should return 400 with candidates
    assert response.status_code == 400
    json_data = response.json
    # Check structured error envelope
    assert "error" in json_data
    assert json_data["error"]["code"] == "MULTIPLE_EMAIL_COLUMNS"
    candidates = json_data["error"]["details"]["email_column_candidates"]
    assert len(candidates) >= 2
    assert "email" in candidates
    assert "contact_email" in candidates


def test_column_detection_no_match(client):
    """Test error when no email column found."""
    csv_content = "name,phone,address\nAlice,123-456,Main St\n"
    data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")

    assert response.status_code == 400
    json_data = response.json
    # Check structured error envelope
    assert "error" in json_data
    assert json_data["error"]["code"] == "NO_EMAIL_COLUMN"
    assert len(json_data["error"]["details"]["email_column_candidates"]) == 0
    assert "available_columns" in json_data["error"]["details"]


def test_column_detection_explicit(client):
    """Test explicit email_column parameter works."""
    csv_content = "name,email,contact_email\nAlice,alice@example.com,alice2@test.com\n"
    data = {
        "file": (io.BytesIO(csv_content.encode()), "test.csv"),
        "email_column": "contact_email",
    }
    response = client.post("/verify", data=data, content_type="multipart/form-data")

    assert response.status_code == 200
    assert response.json.get("email_column") == "contact_email"


def test_download_scores_type(client):
    """Test the new 'scores' download type."""
    csv_content = "name,email,company\nAlice,alice@example.com,Acme\nBob,bob@unknown.io,Tech\n"
    data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    job_id = response.json["job_id"]

    # Wait for completion
    for _ in range(50):
        time.sleep(0.1)
        progress = client.get(f"/progress?job_id={job_id}").json
        if progress["percent"] >= 100:
            break

    # Download scores-only format
    response = client.get(f"/download?job_id={job_id}&type=scores")
    assert response.status_code == 200
    content = response.data.decode()
    lines = content.strip().split("\n")

    # Check headers are scores-only
    headers = [h.strip() for h in lines[0].split(",")]
    assert "email" in headers
    assert "status" in headers
    assert "reason" in headers
    assert "score" in headers
    assert "risk_factors" in headers
    # Should NOT include original columns
    assert "name" not in headers
    assert "company" not in headers


def test_progress_includes_summary(client):
    """Test that /progress includes summary when job is complete."""
    csv_content = "name,email\nAlice,alice@example.com\nBob,bob@unknown.io\n"
    data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    job_id = response.json["job_id"]

    # Wait for completion
    progress = None
    for _ in range(50):
        time.sleep(0.1)
        progress = client.get(f"/progress?job_id={job_id}").json
        if progress["percent"] >= 100:
            break

    assert progress is not None
    assert progress["percent"] >= 100
    assert "summary" in progress

    summary = progress["summary"]
    assert "valid" in summary
    assert "risky" in summary
    assert "invalid" in summary
    assert "avg_score" in summary
    assert "top_risk_factors" in summary


def test_schema_endpoint(client):
    """Test the /schema endpoint."""
    response = client.get("/schema")
    assert response.status_code == 200

    json_data = response.json
    assert "validator_mode" in json_data
    assert json_data["validator_mode"] == "mock"
    assert "scoring_version" in json_data
    assert "download_types" in json_data
    assert "scores" in json_data["download_types"]
    assert "supported_columns" in json_data

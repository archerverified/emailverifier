"""
Tests for error handling in the /verify endpoint.
"""

import io


def test_verify_rejects_non_csv(client):
    """Test that non-CSV files are rejected with 400 error."""
    data = {"file": (io.BytesIO(b"not a csv content"), "test.txt")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")
    assert response.status_code == 400
    assert "error" in response.json
    assert "CSV" in response.json["error"]


def test_verify_rejects_missing_email_column(client):
    """Test that CSV without email column returns 400 with available columns."""
    csv_content = "name,company\nJohn Doe,Acme Inc\nJane Smith,Tech Corp\n"
    data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")
    assert response.status_code == 400
    json_data = response.json
    # Check structured error envelope
    assert "error" in json_data
    assert json_data["error"]["code"] == "NO_EMAIL_COLUMN"
    # Check that error message mentions email column
    error_msg = json_data["error"]["message"].lower()
    assert "email" in error_msg or "column" in error_msg
    # Check that available_columns is returned in details
    assert "available_columns" in json_data["error"]["details"]
    assert "name" in json_data["error"]["details"]["available_columns"]
    assert "company" in json_data["error"]["details"]["available_columns"]
    # Check that email_column_candidates is empty (no matches)
    assert "email_column_candidates" in json_data["error"]["details"]
    assert len(json_data["error"]["details"]["email_column_candidates"]) == 0


def test_verify_rejects_empty_csv(client):
    """Test that empty CSV files are rejected."""
    csv_content = ""
    data = {"file": (io.BytesIO(csv_content.encode()), "empty.csv")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")
    assert response.status_code == 400
    assert "error" in response.json


def test_verify_rejects_no_file(client):
    """Test that request without file is rejected."""
    response = client.post("/verify", data={}, content_type="multipart/form-data")
    assert response.status_code == 400
    assert "error" in response.json


def test_verify_accepts_valid_csv(client):
    """Test that valid CSV with email column is accepted."""
    csv_content = "name,email,company\nJohn,john@example.com,Acme\n"
    data = {"file": (io.BytesIO(csv_content.encode()), "valid.csv")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    assert "job_id" in response.json
    # Verify job_id is a valid UUID format
    job_id = response.json["job_id"]
    assert len(job_id) == 36  # UUID format


def test_verify_accepts_email_column_case_insensitive(client):
    """Test that EMAIL column (uppercase) is also accepted."""
    csv_content = "name,EMAIL,company\nJohn,john@example.com,Acme\n"
    data = {"file": (io.BytesIO(csv_content.encode()), "test.csv")}
    response = client.post("/verify", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    assert "job_id" in response.json

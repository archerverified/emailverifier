"""
Tests for the health check endpoint.
"""


def test_health_endpoint(client):
    """Test that health endpoint returns 200 with JSON status."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_health_endpoint_content_type(client):
    """Test that health endpoint returns JSON content type."""
    response = client.get("/health")
    assert response.content_type == "application/json"

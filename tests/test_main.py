"""Tests for the thin FastAPI skeleton app.

The only requirement for issue #14 is that a deployed instance responds with
HTTP 200 on the root path. The test spins up the FastAPI app using the
TestClient provided by FastAPI and asserts the expected JSON payload.
"""

from fastapi.testclient import TestClient

from app.main import app


def test_root_returns_status_ok():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


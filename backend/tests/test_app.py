"""Tests for the Flask app skeleton itself (creation, health check)."""
from app import create_app


def test_create_app_returns_flask_app():
    app = create_app(db_path=":memory:")
    assert app is not None


def test_health_endpoint_returns_ok():
    app = create_app(db_path=":memory:")
    client = app.test_client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}

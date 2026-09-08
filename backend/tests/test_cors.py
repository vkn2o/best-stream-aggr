"""Tests for cross-origin access to the API.

Regression test for a bug found during full-stack integration testing: a
page on any origin other than the Vite dev proxy's own origin got
`TypeError: Failed to fetch` with no indication it was CORS — Flask sent no
`Access-Control-Allow-Origin` header at all. curl-based checks never catch
this because CORS is enforced by the browser, not the server (see
docs/Decisions.md).
"""
from app import create_app


def client():
    return create_app(db_path=":memory:").test_client()


def test_allows_the_vite_dev_server_origin():
    response = client().get(
        "/api/history", headers={"Origin": "http://localhost:5173"}
    )

    assert response.headers.get("Access-Control-Allow-Origin") == (
        "http://localhost:5173"
    )


def test_does_not_reflect_an_unrecognized_origin():
    response = client().get(
        "/api/history", headers={"Origin": "http://evil.example"}
    )

    assert "Access-Control-Allow-Origin" not in response.headers


def test_preflight_for_search_allows_post_and_content_type():
    response = client().options(
        "/api/search",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )

    assert response.status_code == 200
    assert "POST" in response.headers.get("Access-Control-Allow-Methods", "")


def test_health_endpoint_is_also_reachable_cross_origin():
    response = client().get(
        "/health", headers={"Origin": "http://localhost:5173"}
    )

    assert response.headers.get("Access-Control-Allow-Origin") == (
        "http://localhost:5173"
    )

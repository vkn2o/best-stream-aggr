"""Tests for GET /history."""
import pytest

import scraper
from app import create_app
from scraper import fmhy_source_list

_MARKDOWN = """# ► Streaming Sites

## ▷ Stream Aggregators

* ⭐ **[Alpha](https://alpha.test/)** - Movies / TV
"""


@pytest.fixture(autouse=True)
def stub_fmhy(monkeypatch):
    """/api/search reaches FMHY and IMDb — stub both, keep tests offline."""
    fmhy_source_list.clear_cache()
    monkeypatch.setattr(fmhy_source_list, "fetch_video_markdown", lambda: _MARKDOWN)
    monkeypatch.setattr(scraper, "resolve_title", lambda query: None)
    yield
    fmhy_source_list.clear_cache()


def client():
    app = create_app(db_path=":memory:")
    return app.test_client()


def test_history_with_no_past_searches_returns_empty_list():
    response = client().get("/api/history")

    assert response.status_code == 200
    assert response.get_json() == []


def test_history_returns_past_searches_newest_first():
    c = client()
    c.post("/api/search", json={"query": "First Query"})
    c.post("/api/search", json={"query": "Second Query"})

    response = c.get("/api/history")

    queries = [entry["query"] for entry in response.get_json()]
    assert queries == ["Second Query", "First Query"]


def test_history_entries_include_id_query_and_timestamp():
    c = client()
    c.post("/api/search", json={"query": "The Matrix"})

    [entry] = c.get("/api/history").get_json()

    assert set(entry.keys()) >= {"id", "query", "timestamp"}

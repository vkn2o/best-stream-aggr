"""Tests for GET /api/suggestions — the search box's autocomplete data.

Only the IMDb fetch is stubbed; the real title_lookup parsing runs
underneath, same convention as test_search_route.py.
"""
import requests

from app import create_app
from scraper import title_lookup


def client():
    return create_app(db_path=":memory:").test_client()


def test_query_shorter_than_two_characters_returns_no_suggestions():
    response = client().get("/api/suggestions?q=a")

    assert response.status_code == 200
    assert response.get_json() == {"suggestions": []}


def test_missing_query_returns_no_suggestions():
    response = client().get("/api/suggestions")

    assert response.status_code == 200
    assert response.get_json() == {"suggestions": []}


def test_returns_up_to_five_matches_with_title_year_kind_and_imdb_id(monkeypatch):
    monkeypatch.setattr(
        title_lookup,
        "fetch_suggestions",
        lambda query: {
            "d": [
                {
                    "id": f"tt000000{n}",
                    "l": f"Title {n}",
                    "y": 2000 + n,
                    "qid": "movie",
                    "i": {"imageUrl": f"https://example.test/{n}.jpg"},
                }
                for n in range(8)
            ]
        },
    )

    response = client().get("/api/suggestions?q=title")

    body = response.get_json()
    assert response.status_code == 200
    assert len(body["suggestions"]) == 5
    assert body["suggestions"][0] == {
        "imdb_id": "tt0000000",
        "title": "Title 0",
        "year": 2000,
        "kind": "movie",
        "image_url": "https://example.test/0.jpg",
    }


def test_suggestion_without_an_image_reports_a_null_image_url(monkeypatch):
    monkeypatch.setattr(
        title_lookup,
        "fetch_suggestions",
        lambda query: {"d": [{"id": "tt0133093", "l": "The Matrix", "qid": "movie"}]},
    )

    body = client().get("/api/suggestions?q=matrix").get_json()

    assert body["suggestions"][0]["image_url"] is None


def test_skips_non_watchable_entries_such_as_people(monkeypatch):
    monkeypatch.setattr(
        title_lookup,
        "fetch_suggestions",
        lambda query: {"d": [{"id": "nm0000206", "l": "Keanu Reeves"}]},
    )

    body = client().get("/api/suggestions?q=keanu").get_json()

    assert body["suggestions"] == []


def test_imdb_being_unreachable_degrades_to_an_empty_list_not_an_error(monkeypatch):
    def boom(query):
        raise requests.RequestException("imdb down")

    monkeypatch.setattr(title_lookup, "fetch_suggestions", boom)

    response = client().get("/api/suggestions?q=matrix")

    assert response.status_code == 200
    assert response.get_json() == {"suggestions": []}


def test_an_unexpected_response_shape_degrades_to_an_empty_list_not_a_crash(
    monkeypatch,
):
    monkeypatch.setattr(
        title_lookup, "fetch_suggestions", lambda query: ["not", "a", "dict"]
    )

    response = client().get("/api/suggestions?q=matrix")

    assert response.status_code == 200
    assert response.get_json() == {"suggestions": []}


def test_a_non_json_imdb_response_degrades_to_an_empty_list_not_a_crash(monkeypatch):
    def boom(query):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")

    monkeypatch.setattr(title_lookup, "fetch_suggestions", boom)

    response = client().get("/api/suggestions?q=matrix")

    assert response.status_code == 200
    assert response.get_json() == {"suggestions": []}

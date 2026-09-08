"""Tests for scraper/title_lookup.py — resolving a query to a real title.

Fixtures are trimmed real responses from IMDb's keyless suggestion
endpoint; the network call itself is stubbed to keep tests offline.
"""
import json
from pathlib import Path

import pytest

from scraper import title_lookup
from scraper.title_lookup import (
    ResolvedTitle,
    Suggestion,
    resolve_suggestions,
    resolve_title,
    suggestion_url,
)

_FIXTURES = Path(__file__).parent / "fixtures"
_MATRIX = json.loads((_FIXTURES / "imdb_suggestion_the_matrix.json").read_text())
_BREAKING_BAD = json.loads(
    (_FIXTURES / "imdb_suggestion_breaking_bad.json").read_text()
)


@pytest.fixture
def stub_suggestions(monkeypatch):
    def install(payload):
        monkeypatch.setattr(
            title_lookup, "fetch_suggestions", lambda query: payload
        )

    return install


def test_resolves_a_movie_to_its_imdb_id_title_and_year(stub_suggestions):
    stub_suggestions(_MATRIX)

    resolved = resolve_title("the matrix")

    assert resolved == ResolvedTitle(
        imdb_id="tt0133093", title="The Matrix", year=1999, kind="movie"
    )


def test_resolves_a_tv_series(stub_suggestions):
    stub_suggestions(_BREAKING_BAD)

    resolved = resolve_title("breaking bad")

    assert resolved.imdb_id == "tt0903747"
    assert resolved.kind == "tvSeries"


def test_skips_non_title_entries_such_as_industry_records(stub_suggestions):
    stub_suggestions(_MATRIX)

    resolved = resolve_title("the matrix")

    # "in0000304" is an IMDb industry entry, not a watchable title.
    assert resolved.imdb_id.startswith("tt")


def test_returns_none_when_nothing_title_like_matches(stub_suggestions):
    stub_suggestions({"d": [{"id": "nm0000206", "l": "Keanu Reeves"}]})

    assert resolve_title("keanu reeves") is None


def test_returns_none_for_an_empty_suggestion_payload(stub_suggestions):
    stub_suggestions({"d": []})

    assert resolve_title("zzzzzzzz") is None


def test_suggestion_url_uses_the_first_letter_of_the_query():
    assert suggestion_url("The Matrix").startswith(
        "https://v2.sg.media-imdb.com/suggestion/t/"
    )


def test_suggestion_url_percent_encodes_the_query():
    assert "the%20matrix" in suggestion_url("the matrix").lower()


def test_resolve_title_skips_non_dict_entries_instead_of_crashing(stub_suggestions):
    # Regression test: IMDb changing its response shape (e.g. a stripped
    # entry format) must degrade to "no match", not crash the whole search.
    stub_suggestions({"d": ["not-a-dict", {"id": "tt0133093", "l": "The Matrix", "y": 1999, "qid": "movie"}]})

    resolved = resolve_title("the matrix")

    assert resolved.imdb_id == "tt0133093"


def test_resolve_title_returns_none_when_the_entries_list_is_all_malformed(stub_suggestions):
    stub_suggestions({"d": ["not-a-dict", 42, None]})

    assert resolve_title("the matrix") is None


def test_resolve_title_returns_none_when_the_top_level_payload_is_not_a_dict(
    stub_suggestions,
):
    stub_suggestions(["unexpected", "top-level", "list"])

    assert resolve_title("the matrix") is None


def test_resolve_title_returns_none_when_the_suggestions_key_is_not_a_list(
    stub_suggestions,
):
    stub_suggestions({"d": "not-a-list"})

    assert resolve_title("the matrix") is None


class TestResolveSuggestions:
    """Tests for resolve_suggestions — the /api/suggestions data source."""

    def test_returns_watchable_matches_with_title_year_kind_and_image(
        self, stub_suggestions
    ):
        stub_suggestions(_MATRIX)

        suggestions = resolve_suggestions("matrix")

        assert suggestions[0] == Suggestion(
            imdb_id="tt0133093",
            title="The Matrix",
            year=1999,
            kind="movie",
            image_url=(
                "https://m.media-amazon.com/images/M/"
                "MV5BN2NmN2VhMTQtMDNiOS00NDlhLTliMjgtODE2ZTY0ODQyNDRhXkEyXkFqcGc@._V1_.jpg"
            ),
        )

    def test_skips_industry_records_such_as_actor_and_franchise_entries(
        self, stub_suggestions
    ):
        stub_suggestions(_MATRIX)

        suggestions = resolve_suggestions("matrix")

        # "in0000304" (a franchise record) must not appear.
        assert all(s.imdb_id.startswith("tt") for s in suggestions)

    def test_defaults_to_at_most_five_suggestions(self, stub_suggestions):
        stub_suggestions(
            {
                "d": [
                    {
                        "id": f"tt000000{n}",
                        "l": f"Title {n}",
                        "y": 2000 + n,
                        "qid": "movie",
                    }
                    for n in range(8)
                ]
            }
        )

        suggestions = resolve_suggestions("title")

        assert len(suggestions) == 5

    def test_respects_a_custom_limit(self, stub_suggestions):
        stub_suggestions(_MATRIX)

        suggestions = resolve_suggestions("matrix", limit=1)

        assert len(suggestions) == 1

    def test_entry_with_no_image_gets_a_none_image_url(self, stub_suggestions):
        stub_suggestions(
            {"d": [{"id": "tt0133093", "l": "The Matrix", "qid": "movie"}]}
        )

        [suggestion] = resolve_suggestions("matrix")

        assert suggestion.image_url is None

    def test_entry_with_a_malformed_image_field_gets_a_none_image_url(
        self, stub_suggestions
    ):
        stub_suggestions(
            {
                "d": [
                    {
                        "id": "tt0133093",
                        "l": "The Matrix",
                        "qid": "movie",
                        "i": "not-a-dict",
                    }
                ]
            }
        )

        [suggestion] = resolve_suggestions("matrix")

        assert suggestion.image_url is None

    def test_returns_an_empty_list_for_an_empty_suggestion_payload(
        self, stub_suggestions
    ):
        stub_suggestions({"d": []})

        assert resolve_suggestions("zzzzzzzz") == []

    def test_returns_an_empty_list_when_the_top_level_payload_is_not_a_dict(
        self, stub_suggestions
    ):
        stub_suggestions(["unexpected", "list"])

        assert resolve_suggestions("matrix") == []

    def test_skips_non_dict_entries_instead_of_crashing(self, stub_suggestions):
        stub_suggestions(
            {
                "d": [
                    "not-a-dict",
                    {"id": "tt0133093", "l": "The Matrix", "qid": "movie"},
                ]
            }
        )

        suggestions = resolve_suggestions("matrix")

        assert [s.imdb_id for s in suggestions] == ["tt0133093"]

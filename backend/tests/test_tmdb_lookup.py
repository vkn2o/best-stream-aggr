"""Tests for scraper/tmdb_lookup.py — IMDb id -> TMDB id.

Needed because the sites' player routes key on TMDB ids while the app
resolves IMDb ids. The whole thing is optional: without an API key, or on
any failure, it must return None so links fall back to today's search URLs.
That degradation path is tested first and most, because it is the default
state for anyone who hasn't set up a key.
"""
import pytest
import requests

from scraper import tmdb_lookup
from scraper.tmdb_lookup import TmdbMatch, find_imdb_id, find_tmdb_id

_MATRIX_PAYLOAD = {
    "movie_results": [{"id": 603, "title": "The Matrix"}],
    "tv_results": [],
    "person_results": [],
}
_BREAKING_BAD_PAYLOAD = {
    "movie_results": [],
    "tv_results": [{"id": 1396, "name": "Breaking Bad"}],
}


@pytest.fixture(autouse=True)
def clear_cache():
    tmdb_lookup.clear_cache()
    yield
    tmdb_lookup.clear_cache()


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "test-key")


@pytest.fixture
def stub_find(monkeypatch):
    calls = []

    def install(payload):
        def fake_fetch(imdb_id, api_key):
            calls.append((imdb_id, api_key))
            if isinstance(payload, Exception):
                raise payload
            return payload

        monkeypatch.setattr(tmdb_lookup, "_fetch_find", fake_fetch)

    install.calls = calls
    return install


class TestWithoutAnApiKey:
    def test_returns_none_when_no_key_is_configured(self, monkeypatch, stub_find):
        monkeypatch.delenv("TMDB_API_KEY", raising=False)
        stub_find(_MATRIX_PAYLOAD)

        assert find_tmdb_id("tt0133093") is None

    def test_does_not_call_tmdb_at_all_without_a_key(self, monkeypatch, stub_find):
        monkeypatch.delenv("TMDB_API_KEY", raising=False)
        stub_find(_MATRIX_PAYLOAD)

        find_tmdb_id("tt0133093")

        assert stub_find.calls == []

    def test_an_empty_key_counts_as_no_key(self, monkeypatch, stub_find):
        monkeypatch.setenv("TMDB_API_KEY", "   ")
        stub_find(_MATRIX_PAYLOAD)

        assert find_tmdb_id("tt0133093") is None


class TestResolution:
    def test_resolves_a_movie(self, with_key, stub_find):
        stub_find(_MATRIX_PAYLOAD)

        assert find_tmdb_id("tt0133093") == TmdbMatch(tmdb_id=603, media_type="movie")

    def test_resolves_a_tv_series(self, with_key, stub_find):
        stub_find(_BREAKING_BAD_PAYLOAD)

        assert find_tmdb_id("tt0903747") == TmdbMatch(
            tmdb_id=1396, media_type="tv"
        )

    def test_prefers_a_movie_when_both_kinds_match(self, with_key, stub_find):
        stub_find({"movie_results": [{"id": 1}], "tv_results": [{"id": 2}]})

        assert find_tmdb_id("tt1").media_type == "movie"

    def test_passes_the_configured_key_through(self, with_key, stub_find):
        stub_find(_MATRIX_PAYLOAD)

        find_tmdb_id("tt0133093")

        assert stub_find.calls == [("tt0133093", "test-key")]

    def test_returns_none_when_nothing_matches(self, with_key, stub_find):
        stub_find({"movie_results": [], "tv_results": []})

        assert find_tmdb_id("tt0000000") is None


class TestUntrustedPayloads:
    """TMDB's response shape is not a contract this app controls."""

    @pytest.mark.parametrize(
        "bad",
        [
            None,
            "not-a-dict",
            ["list"],
            {},
            {"movie_results": "not-a-list"},
            {"movie_results": ["not-a-dict"]},
            {"movie_results": [{}]},  # no id
            {"movie_results": [{"id": "603"}]},  # id not an int
            {"movie_results": [{"id": True}]},  # bool is not a real id
        ],
    )
    def test_a_malformed_payload_degrades_to_none(self, with_key, stub_find, bad):
        stub_find(bad)

        assert find_tmdb_id("tt0133093") is None

    def test_a_network_failure_degrades_to_none(self, with_key, stub_find):
        import requests

        stub_find(requests.RequestException("tmdb down"))

        assert find_tmdb_id("tt0133093") is None

    def test_a_non_json_body_degrades_to_none(self, with_key, stub_find):
        stub_find(ValueError("Expecting value: line 1 column 1"))

        assert find_tmdb_id("tt0133093") is None


class TestCaching:
    def test_a_repeated_lookup_does_not_refetch(self, with_key, stub_find):
        stub_find(_MATRIX_PAYLOAD)

        find_tmdb_id("tt0133093")
        find_tmdb_id("tt0133093")

        # IMDb->TMDB mappings don't change; one call is enough.
        assert len(stub_find.calls) == 1

    def test_a_miss_is_cached_too(self, with_key, stub_find):
        stub_find({"movie_results": [], "tv_results": []})

        find_tmdb_id("tt0000000")
        find_tmdb_id("tt0000000")

        assert len(stub_find.calls) == 1


class TestReverseLookup:
    """TMDB id -> IMDb id, so a playback report can name the title it watched.

    The player pages carry a TMDB id in the URL and no IMDb id anywhere, so
    without this every reported session is site-wide evidence only and the
    title-scoped path in telemetry.py is unreachable.
    """

    @pytest.fixture
    def stub_external_ids(self, monkeypatch):
        calls = []

        def install(payload):
            def fake_fetch(tmdb_id, media_type, api_key):
                calls.append((tmdb_id, media_type, api_key))
                if isinstance(payload, Exception):
                    raise payload
                return payload

            monkeypatch.setattr(tmdb_lookup, "_fetch_external_ids", fake_fetch)

        install.calls = calls
        return install

    def test_resolves_a_movie_to_its_imdb_id(self, with_key, stub_external_ids):
        stub_external_ids({"id": 603, "imdb_id": "tt0133093"})

        assert find_imdb_id(603, "movie") == "tt0133093"

    def test_resolves_a_series_to_its_imdb_id(self, with_key, stub_external_ids):
        stub_external_ids({"id": 1396, "imdb_id": "tt0903747"})

        assert find_imdb_id(1396, "tv") == "tt0903747"

    def test_asks_tmdb_for_the_right_media_type(self, with_key, stub_external_ids):
        stub_external_ids({"imdb_id": "tt0903747"})

        find_imdb_id(1396, "tv")

        assert stub_external_ids.calls == [(1396, "tv", "test-key")]

    def test_returns_none_without_a_key(self, monkeypatch, stub_external_ids):
        monkeypatch.delenv("TMDB_API_KEY", raising=False)
        stub_external_ids({"imdb_id": "tt0133093"})

        assert find_imdb_id(603, "movie") is None
        assert stub_external_ids.calls == []

    def test_rejects_an_unknown_media_type(self, with_key, stub_external_ids):
        stub_external_ids({"imdb_id": "tt0133093"})

        assert find_imdb_id(603, "person") is None
        assert stub_external_ids.calls == []

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"imdb_id": None},
            {"imdb_id": ""},
            {"imdb_id": 603},
            {"imdb_id": "nm0000206"},  # a person, not a title
            [],
            "not json",
        ],
    )
    def test_an_unexpected_shape_is_no_answer(
        self, with_key, stub_external_ids, payload
    ):
        stub_external_ids(payload)

        assert find_imdb_id(603, "movie") is None

    def test_a_network_failure_is_no_answer(self, with_key, stub_external_ids):
        stub_external_ids(requests.RequestException("boom"))

        assert find_imdb_id(603, "movie") is None

    def test_caches_the_answer(self, with_key, stub_external_ids):
        stub_external_ids({"imdb_id": "tt0133093"})

        find_imdb_id(603, "movie")
        find_imdb_id(603, "movie")

        assert len(stub_external_ids.calls) == 1

    def test_a_movie_and_a_series_id_do_not_collide(
        self, with_key, stub_external_ids
    ):
        stub_external_ids({"imdb_id": "tt0133093"})
        find_imdb_id(603, "movie")

        stub_external_ids({"imdb_id": "tt0903747"})

        assert find_imdb_id(603, "tv") == "tt0903747"

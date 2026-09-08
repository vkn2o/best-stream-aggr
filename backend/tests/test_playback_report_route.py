"""Tests for POST /api/playback-report.

This endpoint accepts numbers from a userscript running on a third-party
page, so its input is about as untrusted as input gets. A malformed or
hostile payload must be rejected outright rather than stored: a bad row
here becomes a confident wrong recommendation later.
"""
import pytest

from app import create_app
from db.store import playback_stats
from routes import playback_report


@pytest.fixture
def app():
    return create_app(db_path=":memory:")


@pytest.fixture
def client(app):
    return app.test_client()


def _payload(**kw):
    body = {
        "site": "flixer.gd",
        "imdb_id": "tt0133093",
        "started": True,
        "startup_ms": 1200,
        "rebuffer_count": 1,
        "rebuffer_ms": 400,
        "observed_ms": 30000,
    }
    body.update(kw)
    return body


def test_a_valid_report_is_accepted_and_stored(app, client):
    response = client.post("/api/playback-report", json=_payload())

    assert response.status_code == 201
    with app.app_context():
        stats = playback_stats(app.config["DB_CONN"], site="flixer.gd")
    assert stats["sample_size"] == 1
    assert stats["startup_ms"] == 1200


def test_a_session_that_never_started_is_storable(client):
    response = client.post(
        "/api/playback-report", json=_payload(started=False, startup_ms=None)
    )

    assert response.status_code == 201


def test_a_report_without_a_title_is_accepted(client):
    assert (
        client.post("/api/playback-report", json=_payload(imdb_id=None)).status_code
        == 201
    )


@pytest.mark.parametrize(
    "bad",
    [
        {"site": ""},
        {"site": 123},
        {"started": "yes"},
        {"rebuffer_count": -1},
        {"rebuffer_ms": -5},
        {"observed_ms": 0},
        {"observed_ms": -1},
        {"startup_ms": -10},
        {"startup_ms": "fast"},
        {"rebuffer_count": True},
        {"rebuffer_count": 1.5},
        {"imdb_id": 42},
    ],
)
def test_a_malformed_report_is_rejected(client, bad):
    response = client.post("/api/playback-report", json=_payload(**bad))

    assert response.status_code == 400


def test_a_missing_field_is_rejected(client):
    body = _payload()
    del body["observed_ms"]

    assert client.post("/api/playback-report", json=body).status_code == 400


def test_a_non_json_body_is_rejected(client):
    assert client.post("/api/playback-report").status_code == 400


def test_a_rejected_report_is_not_stored(app, client):
    client.post("/api/playback-report", json=_payload(rebuffer_count=-1))

    with app.app_context():
        assert playback_stats(app.config["DB_CONN"], site="flixer.gd") is None


def test_reported_playback_reaches_the_search_ranking(app, client, monkeypatch):
    """The whole point: real sessions change what gets recommended."""
    import scraper
    from scraper import fmhy_source_list
    from scraper.title_lookup import ResolvedTitle

    markdown = (
        "# ► Streaming Sites\n\n## ▷ Stream Aggregators\n\n"
        "* ⭐ **[Flixer](https://flixer.gd)** - Movies / TV\n"
        "* [Beta](https://beta.test/) - Movies / TV\n"
    )
    fmhy_source_list.clear_cache()
    monkeypatch.setattr(fmhy_source_list, "fetch_video_markdown", lambda: markdown)
    monkeypatch.setattr(
        scraper,
        "resolve_title",
        lambda q: ResolvedTitle(
            imdb_id="tt0133093", title="The Matrix", year=1999, kind="movie"
        ),
    )

    for _ in range(3):
        client.post(
            "/api/playback-report",
            json=_payload(started=False, startup_ms=None),
        )

    body = client.post("/api/search", json={"query": "matrix"}).get_json()
    fmhy_source_list.clear_cache()

    # Three reported sessions that never played is real evidence against
    # Flixer, so the untested site must be recommended instead.
    assert body["top_source"]["site_name"] == "Beta"


class TestTitleFromATmdbReference:
    """A player page names its title with a TMDB id, not an IMDb one.

    Flixer's `/watch/movie/603` carries no `tt` id anywhere in the page, so
    without mapping the reference back every session lands as site-wide
    evidence and telemetry's title-scoped path can never fire.
    """

    @pytest.fixture
    def stub_lookup(self, monkeypatch):
        calls = []

        def install(answer):
            def fake(tmdb_id, media_type):
                calls.append((tmdb_id, media_type))
                return answer

            monkeypatch.setattr(playback_report, "find_imdb_id", fake)

        install.calls = calls
        return install

    def _tmdb_payload(self, **kw):
        body = _payload(imdb_id=None, tmdb_id=603, media_type="movie")
        body.update(kw)
        return body

    def test_a_tmdb_reference_is_resolved_and_stored_as_the_title(
        self, app, client, stub_lookup
    ):
        stub_lookup("tt0133093")

        response = client.post("/api/playback-report", json=self._tmdb_payload())

        assert response.status_code == 201
        stats = playback_stats(
            app.config["DB_CONN"], site="flixer.gd", imdb_id="tt0133093"
        )
        assert stats["sample_size"] == 1

    def test_it_asks_about_the_right_title(self, client, stub_lookup):
        stub_lookup("tt0903747")

        client.post(
            "/api/playback-report",
            json=self._tmdb_payload(tmdb_id=1396, media_type="tv"),
        )

        assert stub_lookup.calls == [(1396, "tv")]

    def test_an_unresolvable_reference_still_stores_the_session(
        self, app, client, stub_lookup
    ):
        # No TMDB key, or TMDB down. The measurement is real either way and
        # is still worth having as site-wide evidence.
        stub_lookup(None)

        response = client.post("/api/playback-report", json=self._tmdb_payload())

        assert response.status_code == 201
        assert playback_stats(app.config["DB_CONN"], site="flixer.gd")["sample_size"] == 1

    def test_an_explicit_imdb_id_wins_and_costs_no_lookup(self, client, stub_lookup):
        stub_lookup("tt9999999")

        client.post(
            "/api/playback-report",
            json=_payload(imdb_id="tt0133093", tmdb_id=603, media_type="movie"),
        )

        assert stub_lookup.calls == []

    @pytest.mark.parametrize(
        "overrides",
        [
            {"tmdb_id": "603"},
            {"tmdb_id": 0},
            {"tmdb_id": -1},
            {"tmdb_id": True},
            {"tmdb_id": 1.5},
            {"media_type": "person"},
            {"media_type": 7},
            {"tmdb_id": 603, "media_type": None},  # half a reference
            {"tmdb_id": None, "media_type": "movie"},
        ],
    )
    def test_a_malformed_reference_is_rejected(self, client, stub_lookup, overrides):
        stub_lookup("tt0133093")

        response = client.post(
            "/api/playback-report", json=self._tmdb_payload(**overrides)
        )

        assert response.status_code == 400

    def test_a_report_with_no_title_reference_at_all_is_still_fine(
        self, client, stub_lookup
    ):
        stub_lookup("tt0133093")

        response = client.post("/api/playback-report", json=_payload(imdb_id=None))

        assert response.status_code == 201
        assert stub_lookup.calls == []

"""Tests for POST /api/search.

Only the network fetch is stubbed — the route runs the real FMHY markdown
parser and the real scoring beneath it, so these exercise the whole slice
end-to-end minus the one non-deterministic boundary.
"""
import pytest
import requests

import scraper
from app import create_app
from scraper import availability, fmhy_source_list, playback
from scraper.title_lookup import ResolvedTitle

# Flixer has a verified search route in the adapter table; Beta does not,
# so it should fall back to its home page.
_MARKDOWN = """# ► Streaming Sites

## ▷ Stream Aggregators

* ⭐ **[Flixer](https://flixer.gd)** - Movies / TV
* [Beta](https://beta.test/) - Movies / TV
"""

_RESOLVED = ResolvedTitle(
    imdb_id="tt0133093", title="The Matrix", year=1999, kind="movie"
)


@pytest.fixture(autouse=True)
def stub_fmhy(monkeypatch):
    fmhy_source_list.clear_cache()
    monkeypatch.setattr(fmhy_source_list, "fetch_video_markdown", lambda: _MARKDOWN)
    monkeypatch.setattr(scraper, "resolve_title", lambda query: _RESOLVED)
    yield
    fmhy_source_list.clear_cache()


@pytest.fixture
def client():
    return create_app(db_path=":memory:").test_client()


def test_search_returns_201_with_a_deep_link_to_the_searched_title(client):
    response = client.post("/api/search", json={"query": "matrix"})

    assert response.status_code == 201
    top = response.get_json()["top_source"]
    assert top["url"] == "https://flixer.gd/search?q=The+Matrix"
    assert top["is_deep_link"] is True


def test_search_result_names_the_site_and_its_component_scores(client):
    body = client.post("/api/search", json={"query": "matrix"}).get_json()

    top = body["top_source"]
    assert top["site_name"] == "Flixer"
    assert top["starred"] is True
    assert set(top["scores"]) == {"reliability", "subtitle", "latency"}


def test_search_reports_the_matched_title_and_subtitle_status(client):
    body = client.post("/api/search", json={"query": "matrix"}).get_json()

    assert body["matched_title"] == "The Matrix"
    assert body["year"] == 1999
    assert body["top_source"]["subtitle_status"] == "unknown"


def test_search_persists_the_matched_title(client):
    client.post("/api/search", json={"query": "matrix"})

    [entry] = client.get("/api/history").get_json()

    assert entry["matched_title"] == "The Matrix"


def test_search_returns_the_search_history_alongside_the_result(client):
    client.post("/api/search", json={"query": "Inception"})

    body = client.post("/api/search", json={"query": "The Matrix"}).get_json()

    assert [entry["query"] for entry in body["history"]] == [
        "The Matrix",
        "Inception",
    ]


def test_search_persists_the_chosen_source_and_score(client):
    client.post("/api/search", json={"query": "The Matrix"})

    [entry] = client.get("/api/history").get_json()

    assert entry["query"] == "The Matrix"
    assert entry["source"] == "https://flixer.gd/search?q=The+Matrix"
    assert entry["score"] > 0


def test_search_with_missing_query_field_returns_400(client):
    assert client.post("/api/search", json={}).status_code == 400


def test_search_with_empty_query_string_returns_400(client):
    assert client.post("/api/search", json={"query": "   "}).status_code == 400


def test_search_with_no_json_body_returns_400(client):
    assert client.post("/api/search").status_code == 400


def test_search_returns_502_when_fmhy_is_unreachable(client, monkeypatch):
    def boom():
        raise requests.RequestException("network down")

    monkeypatch.setattr(fmhy_source_list, "fetch_video_markdown", boom)

    assert client.post("/api/search", json={"query": "The Matrix"}).status_code == 502


def test_search_returns_502_when_fmhy_lists_no_streaming_sites(client, monkeypatch):
    monkeypatch.setattr(
        fmhy_source_list, "fetch_video_markdown", lambda: "# ► Download Sites\n"
    )

    assert client.post("/api/search", json={"query": "The Matrix"}).status_code == 502


def test_search_does_not_persist_a_query_it_could_not_resolve(client, monkeypatch):
    def boom():
        raise requests.RequestException("network down")

    monkeypatch.setattr(fmhy_source_list, "fetch_video_markdown", boom)
    client.post("/api/search", json={"query": "The Matrix"})

    assert client.get("/api/history").get_json() == []


def test_search_also_returns_the_best_directly_linkable_source(client):
    body = client.post("/api/search", json={"query": "matrix"}).get_json()

    # Beta ranks below Flixer but has no verified search route, so the
    # deep-linkable pick must be Flixer.
    assert body["best_deep_link"]["url"] == "https://flixer.gd/search?q=The+Matrix"
    assert body["best_deep_link"]["is_deep_link"] is True


class TestPerTitleAvailability:
    """Regression tests for the "same two sites for every search" bug.

    Before task S3 the scorer had no title-derived input at all, so every
    query returned an identical winner no matter what was searched. These
    drive the real detector and the real scorer; only the browser render is
    stubbed.
    """

    _HIT = 'Results for:\n"x"\n\n59 results found\n\nNo more results'
    _MISS = 'Results for:\n"x"\n\n0 results found\n\nNo results found'

    @pytest.fixture
    def probing_client(self, monkeypatch):
        """A client with availability probing on and the browser stubbed."""

        def install(pages: dict[str, str]):
            def fake_render(url, timeout_ms):
                for fragment, text in pages.items():
                    if fragment in url:
                        return text
                raise RuntimeError(f"unexpected probe url: {url}")

            monkeypatch.setattr(availability, "_render_page_text", fake_render)
            return create_app(
                db_path=":memory:", probe_availability=True
            ).test_client()

        return install

    def test_a_site_that_has_the_title_wins_over_fmhys_top_general_pick(
        self, probing_client
    ):
        client = probing_client({"flixer.gd": self._HIT})

        body = client.post("/api/search", json={"query": "matrix"}).get_json()

        assert body["top_source"]["site_name"] == "Flixer"
        assert body["top_source"]["availability"] == "available"
        assert body["top_source"]["result_count"] == 59

    def test_a_site_that_lacks_the_title_loses_to_an_unprobed_site(
        self, probing_client
    ):
        client = probing_client({"flixer.gd": self._MISS})

        body = client.post("/api/search", json={"query": "matrix"}).get_json()

        # Flixer is starred and better placed, but it demonstrably doesn't
        # have this title, so the unprobed site must win instead.
        assert body["top_source"]["site_name"] == "Beta"

    def test_two_different_titles_produce_two_different_top_sources(
        self, monkeypatch
    ):
        """The exact bug, end to end: same site list, different answers.

        Flixer has "matrix" but not "obscure thing", so the two searches must
        not return the same winning source.
        """
        def fake_render(url, timeout_ms):
            has_it = "Matrix" in url or "matrix" in url
            return (
                'Results for:\n\n59 results found'
                if has_it
                else 'Results for:\n\n0 results found\n\nNo results found'
            )

        monkeypatch.setattr(availability, "_render_page_text", fake_render)
        monkeypatch.setattr(scraper, "resolve_title", lambda query: None)
        client = create_app(
            db_path=":memory:", probe_availability=True
        ).test_client()

        found = client.post("/api/search", json={"query": "matrix"}).get_json()
        missing = client.post(
            "/api/search", json={"query": "obscure thing"}
        ).get_json()

        assert found["top_source"]["site_name"] == "Flixer"
        assert missing["top_source"]["site_name"] == "Beta"
        assert (
            found["top_source"]["site_name"] != missing["top_source"]["site_name"]
        )

    def test_probing_is_off_by_default_so_a_search_never_launches_a_browser(
        self, client
    ):
        # The default client would raise from conftest's browser guard if the
        # route probed, so a clean 201 proves it didn't.
        response = client.post("/api/search", json={"query": "matrix"})

        assert response.status_code == 201
        assert response.get_json()["top_source"]["availability"] == "unknown"

    def test_a_probe_failure_leaves_the_search_working(self, monkeypatch):
        def boom(url, timeout_ms):
            raise RuntimeError("browser crashed")

        monkeypatch.setattr(availability, "_render_page_text", boom)
        client = create_app(
            db_path=":memory:", probe_availability=True
        ).test_client()

        response = client.post("/api/search", json={"query": "matrix"})

        assert response.status_code == 201
        assert response.get_json()["top_source"]["availability"] == "unknown"


class TestPlaybackProbing:
    """Task S4 wiring: measured playback reaches the response and the ranking."""

    _AVAILABLE = 'Results for:\n\n59 results found\n\nNo more results'

    @pytest.fixture
    def playback_client(self, monkeypatch):
        class _WorkingAdapter:
            """Stands in for a site whose player we can reach.

            The real Flixer adapter is deliberately disabled (no route to a
            player was found), so these tests inject a usable one to exercise
            the wiring rather than the current state of a third-party site.
            """

            domain = "flixer.gd"
            enabled = True

            def open_player(self, page, title):
                return True

        def install(raw_metrics):
            monkeypatch.setattr(
                availability, "_render_page_text", lambda url, timeout_ms: self._AVAILABLE
            )
            monkeypatch.setattr(
                playback, "_PLAYBACK_ADAPTERS", {"flixer.gd": _WorkingAdapter()}
            )

            def fake_measure(url, title, adapter, observation_ms):
                if isinstance(raw_metrics, Exception):
                    raise raw_metrics
                return raw_metrics

            monkeypatch.setattr(playback, "_measure_playback", fake_measure)
            return create_app(db_path=":memory:", probe_playback=True).test_client()

        return install

    def test_measured_playback_is_reported_on_the_source(self, playback_client):
        client = playback_client(
            {
                "started": True,
                "startupMs": 900,
                "rebufferCount": 0,
                "rebufferMs": 0,
            }
        )

        top = client.post("/api/search", json={"query": "matrix"}).get_json()[
            "top_source"
        ]

        assert top["site_name"] == "Flixer"
        assert top["playback"]["started"] is True
        assert top["playback"]["startup_ms"] == 900
        assert top["playback"]["rebuffer_count"] == 0

    def test_a_source_that_never_played_loses_to_an_unmeasured_one(
        self, playback_client
    ):
        client = playback_client(
            {
                "started": False,
                "startupMs": None,
                "rebufferCount": 0,
                "rebufferMs": 0,
            }
        )

        body = client.post("/api/search", json={"query": "matrix"}).get_json()

        # Flixer has the title but demonstrably won't play it, so the
        # untested site must be recommended instead.
        assert body["top_source"]["site_name"] == "Beta"

    def test_unmeasured_playback_serializes_as_null_not_as_good_playback(
        self, playback_client
    ):
        client = playback_client(None)  # adapter reached no player

        top = client.post("/api/search", json={"query": "matrix"}).get_json()[
            "top_source"
        ]

        assert top["playback"] is None

    def test_a_playback_failure_still_returns_a_normal_result(self, playback_client):
        client = playback_client(RuntimeError("player crashed"))

        response = client.post("/api/search", json={"query": "matrix"})

        assert response.status_code == 201
        assert response.get_json()["top_source"]["playback"] is None

    def test_playback_probing_is_off_by_default(self, client):
        # conftest's browser guard would fire if the route measured playback.
        response = client.post("/api/search", json={"query": "matrix"})

        assert response.status_code == 201
        assert response.get_json()["top_source"]["playback"] is None

    def test_enabling_playback_implies_availability_probing(self):
        app = create_app(db_path=":memory:", probe_playback=True)

        # Playback only measures sources confirmed to have the title, so
        # without availability probing it would silently measure nothing.
        assert app.config["PROBE_AVAILABILITY"] is True


def test_best_deep_link_is_null_when_no_candidate_site_can_be_linked_into(
    client, monkeypatch
):
    monkeypatch.setattr(
        fmhy_source_list,
        "fetch_video_markdown",
        lambda: "# ► Streaming Sites\n\n## ▷ Stream Aggregators\n\n"
        "* ⭐ **[Beta](https://beta.test/)** - Movies\n",
    )

    body = client.post("/api/search", json={"query": "matrix"}).get_json()

    assert body["best_deep_link"] is None

"""Tests for telemetry.py — turning reported sessions into ranking evidence.

The honesty rules under test:
  * a handful of sessions is not evidence — below MIN_SAMPLE_SIZE, stay
    "unknown" rather than ranking on noise;
  * site-wide data must never be labelled as being about this title.
"""
import sqlite3

import pytest

import telemetry
from db.store import add_playback_report, init_db
from scraper import Candidate


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    init_db(connection)
    return connection


def _report(conn, site="flixer.gd", imdb_id="tt0133093", **kw):
    defaults = dict(
        started=True, startup_ms=1200, rebuffer_count=1,
        rebuffer_ms=500, observed_ms=30000,
    )
    defaults.update(kw)
    add_playback_report(conn, site=site, imdb_id=imdb_id, **defaults)


def _candidate(url="https://flixer.gd/watch/movie/603", imdb_id="tt0133093"):
    return Candidate(
        title="The Matrix", url=url, site_name="Flixer", imdb_id=imdb_id
    )


class TestMinimumSample:
    def test_no_reports_means_no_metrics(self, conn):
        assert telemetry.metrics_for(conn, "flixer.gd", "tt0133093") is None

    def test_too_few_reports_stay_unknown(self, conn):
        for _ in range(telemetry.MIN_SAMPLE_SIZE - 1):
            _report(conn)

        # One or two sessions on a flaky wifi are not evidence about a site.
        assert telemetry.metrics_for(conn, "flixer.gd", "tt0133093") is None

    def test_enough_reports_become_measured_metrics(self, conn):
        for _ in range(telemetry.MIN_SAMPLE_SIZE):
            _report(conn)

        metrics = telemetry.metrics_for(conn, "flixer.gd", "tt0133093")

        assert metrics.status == "measured"
        assert metrics.started is True
        assert metrics.startup_ms == 1200
        assert metrics.sample_size == telemetry.MIN_SAMPLE_SIZE


class TestScope:
    def test_title_specific_data_is_labelled_as_such(self, conn):
        for _ in range(3):
            _report(conn, imdb_id="tt0133093")

        metrics = telemetry.metrics_for(conn, "flixer.gd", "tt0133093")

        assert metrics.scope == "title"
        assert metrics.provenance == "reported"

    def test_falls_back_to_site_wide_data_and_says_so(self, conn):
        for _ in range(3):
            _report(conn, imdb_id="tt9999999")  # a different title

        metrics = telemetry.metrics_for(conn, "flixer.gd", "tt0133093")

        # Useful, but it is NOT evidence about this title and must not
        # claim to be.
        assert metrics.scope == "site"

    def test_title_data_is_preferred_when_there_is_enough_of_it(self, conn):
        for _ in range(5):
            _report(conn, imdb_id="tt9999999", startup_ms=8000)
        for _ in range(3):
            _report(conn, imdb_id="tt0133093", startup_ms=1000)

        metrics = telemetry.metrics_for(conn, "flixer.gd", "tt0133093")

        assert metrics.scope == "title"
        assert metrics.startup_ms == 1000

    def test_a_candidate_with_no_imdb_id_can_still_use_site_data(self, conn):
        for _ in range(3):
            _report(conn)

        metrics = telemetry.metrics_for(conn, "flixer.gd", None)

        assert metrics.scope == "site"


class TestAnnotation:
    def test_annotates_a_candidate_from_its_domain(self, conn):
        for _ in range(3):
            _report(conn)

        [candidate] = telemetry.annotate_reported_playback(conn, [_candidate()])

        assert candidate.playback.provenance == "reported"

    def test_leaves_a_candidate_alone_when_there_is_no_evidence(self, conn):
        [candidate] = telemetry.annotate_reported_playback(conn, [_candidate()])

        assert candidate.playback is None

    def test_does_not_overwrite_a_directly_probed_measurement(self, conn):
        from scraper.playback import PlaybackMetrics

        for _ in range(3):
            _report(conn)
        candidate = _candidate()
        candidate.playback = PlaybackMetrics(status="measured", started=True)

        telemetry.annotate_reported_playback(conn, [candidate])

        # A probe watched this exact stream; reports are the fallback.
        assert candidate.playback.provenance == "probed"

    def test_matches_reports_to_the_right_site(self, conn):
        for _ in range(3):
            _report(conn, site="other.test")

        [candidate] = telemetry.annotate_reported_playback(conn, [_candidate()])

        assert candidate.playback is None

"""Tests for the playback_reports table in db/store.py.

Real in-memory SQLite, no mocks — same convention as test_store.py.

These rows are the only source of *real* playback evidence the app has, so
the aggregate they feed into ranking has to be careful: bounded reads, and
enough of a sample that one unlucky session can't condemn a source.
"""
import sqlite3

import pytest

from db.store import add_playback_report, init_db, playback_stats


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    init_db(connection)
    return connection


def _report(conn, site="flixer.gd", imdb_id="tt0133093", started=True,
            startup_ms=1000, rebuffer_count=0, rebuffer_ms=0, observed_ms=30000):
    return add_playback_report(
        conn, site=site, imdb_id=imdb_id, started=started,
        startup_ms=startup_ms, rebuffer_count=rebuffer_count,
        rebuffer_ms=rebuffer_ms, observed_ms=observed_ms,
    )


def test_a_report_round_trips(conn):
    row = _report(conn)

    assert row["site"] == "flixer.gd"
    assert row["imdb_id"] == "tt0133093"
    assert row["started"] == 1
    assert row["startup_ms"] == 1000
    assert row["timestamp"]


def test_a_report_without_a_title_is_allowed(conn):
    # A viewer may land on a player we can't tie back to an IMDb id; the
    # session is still useful as site-wide evidence.
    row = _report(conn, imdb_id=None)

    assert row["imdb_id"] is None


def test_stats_are_none_when_a_site_has_no_reports(conn):
    assert playback_stats(conn, site="flixer.gd") is None


def test_stats_aggregate_the_reports_for_a_site(conn):
    _report(conn, startup_ms=1000, rebuffer_count=0, rebuffer_ms=0)
    _report(conn, startup_ms=2000, rebuffer_count=2, rebuffer_ms=1000)

    stats = playback_stats(conn, site="flixer.gd")

    assert stats["sample_size"] == 2
    assert stats["startup_ms"] == 1500
    assert stats["rebuffer_count"] == 1
    assert stats["rebuffer_ms"] == 500
    assert stats["started"] is True


def test_stats_keep_a_rebuffer_that_averages_below_one(conn):
    # One stall across five sessions is a real measurement. Rounding the
    # average to a whole number erased it, and the UI then said "no
    # rebuffering" about a session set that demonstrably stalled - found
    # against live reported data, not a hypothetical.
    for _ in range(4):
        _report(conn, rebuffer_count=0, rebuffer_ms=0)
    _report(conn, rebuffer_count=1, rebuffer_ms=627)

    stats = playback_stats(conn, site="flixer.gd")

    assert stats["rebuffer_count"] > 0
    assert stats["rebuffer_ms"] > 0


def test_stats_can_be_scoped_to_one_title(conn):
    _report(conn, imdb_id="tt0133093", startup_ms=1000)
    _report(conn, imdb_id="tt0903747", startup_ms=9000)

    stats = playback_stats(conn, site="flixer.gd", imdb_id="tt0133093")

    assert stats["sample_size"] == 1
    assert stats["startup_ms"] == 1000


def test_stats_ignore_other_sites(conn):
    _report(conn, site="flixer.gd", startup_ms=1000)
    _report(conn, site="other.test", startup_ms=9000)

    assert playback_stats(conn, site="flixer.gd")["sample_size"] == 1


def test_started_is_false_only_when_no_session_ever_played(conn):
    _report(conn, started=False, startup_ms=None)
    _report(conn, started=False, startup_ms=None)

    assert playback_stats(conn, site="flixer.gd")["started"] is False


def test_one_successful_session_means_the_source_can_play(conn):
    _report(conn, started=False, startup_ms=None)
    _report(conn, started=True, startup_ms=1200)

    stats = playback_stats(conn, site="flixer.gd")

    assert stats["started"] is True
    # A failed session contributes no startup time to average.
    assert stats["startup_ms"] == 1200


def test_stats_read_is_bounded(conn):
    for _ in range(10):
        _report(conn, startup_ms=1000)

    stats = playback_stats(conn, site="flixer.gd", limit=4)

    # Never aggregate an unbounded number of rows (docs/Constraints.md #4).
    assert stats["sample_size"] == 4


def test_stats_use_the_most_recent_reports(conn):
    for _ in range(3):
        _report(conn, startup_ms=5000)
    for _ in range(3):
        _report(conn, startup_ms=1000)

    stats = playback_stats(conn, site="flixer.gd", limit=3)

    # A site that has since got faster shouldn't be judged on old sessions.
    assert stats["startup_ms"] == 1000

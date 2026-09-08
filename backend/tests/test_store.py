"""Tests for db/store.py — the searches table CRUD layer.

Uses a real in-memory SQLite connection (no mocks) per test-driven-development's
"prefer real implementations" guidance: sqlite3.connect(":memory:") is fast,
isolated, and exercises real SQL rather than a fake.
"""
import sqlite3

import pytest

from db.store import add_search, init_db, list_searches


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    init_db(connection)
    yield connection
    connection.close()


def test_init_db_creates_searches_table(conn):
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='searches'"
    ).fetchall()
    assert len(tables) == 1


def test_add_search_persists_query_with_id_and_timestamp(conn):
    row = add_search(conn, query="The Matrix")

    assert row["id"] is not None
    assert row["query"] == "The Matrix"
    assert row["timestamp"] is not None


def test_list_searches_returns_empty_list_when_no_searches(conn):
    assert list_searches(conn) == []


def test_list_searches_returns_newest_first(conn):
    add_search(conn, query="First Query")
    add_search(conn, query="Second Query")

    results = list_searches(conn)

    assert [r["query"] for r in results] == ["Second Query", "First Query"]


def test_list_searches_includes_id_query_and_timestamp_fields(conn):
    add_search(conn, query="The Matrix")

    [result] = list_searches(conn)

    assert set(result.keys()) >= {"id", "query", "timestamp"}


def test_add_search_defaults_matched_title_source_and_score_to_none(conn):
    row = add_search(conn, query="The Matrix")

    assert row["matched_title"] is None
    assert row["source"] is None
    assert row["score"] is None


def test_add_search_persists_matched_title_source_and_score_when_given(conn):
    row = add_search(
        conn,
        query="The Matrix",
        matched_title="The Matrix (1999)",
        source="example-streaming-site.com",
        score=0.87,
    )

    assert row["matched_title"] == "The Matrix (1999)"
    assert row["source"] == "example-streaming-site.com"
    assert row["score"] == 0.87


def test_list_searches_includes_matched_title_source_and_score_fields(conn):
    add_search(conn, query="The Matrix")

    [result] = list_searches(conn)

    assert set(result.keys()) >= {"matched_title", "source", "score"}


def test_list_searches_defaults_to_a_bounded_number_of_rows(conn):
    # Regression test: with no LIMIT, /api/history returned and the
    # frontend rendered every search ever made — unbounded growth with no
    # pagination (a real perf/scalability finding, not hypothetical: the
    # dev database already had a handful of rows from manual testing).
    for i in range(60):
        add_search(conn, query=f"Query {i}")

    results = list_searches(conn)

    assert len(results) == 50


def test_list_searches_accepts_a_custom_limit(conn):
    for i in range(10):
        add_search(conn, query=f"Query {i}")

    assert len(list_searches(conn, limit=3)) == 3


def test_list_searches_with_a_bounded_limit_still_returns_newest_first(conn):
    add_search(conn, query="First Query")
    add_search(conn, query="Second Query")

    [newest] = list_searches(conn, limit=1)

    assert newest["query"] == "Second Query"

"""SQLite access layer for the `searches` table.

Functions here are pure over a passed-in sqlite3.Connection — no hidden
global connection state — so tests can use sqlite3.connect(":memory:")
directly instead of a fake or mock (see test-driven-development's
"prefer real implementations" guidance).
"""
import sqlite3
from pathlib import Path

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# Without a cap, /api/history returns and the frontend renders every search
# ever made — unbounded growth with no pagination. This is a personal-use
# app with no delete endpoint yet, so history only grows; 50 is generous
# for "recent searches" while keeping both the query and the render bounded.
DEFAULT_HISTORY_LIMIT = 50

# How many recent playback reports an aggregate may read. Bounded for the
# same reason as DEFAULT_HISTORY_LIMIT, and small enough that a site which
# has since improved isn't judged forever on old sessions.
DEFAULT_REPORT_SAMPLE_LIMIT = 20


def init_db(conn: sqlite3.Connection) -> None:
    """Create the `searches` table if it doesn't already exist."""
    conn.executescript(_SCHEMA_PATH.read_text())
    conn.commit()


def add_search(
    conn: sqlite3.Connection,
    query: str,
    matched_title: str | None = None,
    source: str | None = None,
    score: float | None = None,
) -> sqlite3.Row:
    """Insert a new search and return the persisted row.

    `matched_title`, `source`, and `score` are optional because they're
    only known once the scraper/scoring layer (task B4) picks a winning
    candidate for the query — a plain query-only search still persists.
    """
    cursor = conn.execute(
        "INSERT INTO searches (query, matched_title, source, score) "
        "VALUES (?, ?, ?, ?)",
        (query, matched_title, source, score),
    )
    conn.commit()
    return conn.execute(
        "SELECT id, query, matched_title, source, score, timestamp "
        "FROM searches WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()


def list_searches(
    conn: sqlite3.Connection, limit: int = DEFAULT_HISTORY_LIMIT
) -> list[sqlite3.Row]:
    """Return the most recent `limit` searches, newest first."""
    return conn.execute(
        "SELECT id, query, matched_title, source, score, timestamp "
        "FROM searches ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def add_playback_report(
    conn: sqlite3.Connection,
    site: str,
    imdb_id: str | None,
    started: bool,
    startup_ms: int | None,
    rebuffer_count: int,
    rebuffer_ms: int,
    observed_ms: int,
) -> sqlite3.Row:
    """Store one measured playback session reported by a viewer's browser."""
    cursor = conn.execute(
        "INSERT INTO playback_reports "
        "(site, imdb_id, started, startup_ms, rebuffer_count, rebuffer_ms, "
        " observed_ms) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            site,
            imdb_id,
            1 if started else 0,
            startup_ms,
            rebuffer_count,
            rebuffer_ms,
            observed_ms,
        ),
    )
    conn.commit()
    return conn.execute(
        "SELECT * FROM playback_reports WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()


def playback_stats(
    conn: sqlite3.Connection,
    site: str,
    imdb_id: str | None = None,
    limit: int = DEFAULT_REPORT_SAMPLE_LIMIT,
) -> dict | None:
    """Aggregate recent playback reports for a site, or None if there are none.

    Pass `imdb_id` to scope to one title; omit it for site-wide evidence.
    The caller must not present the second as if it were the first.

    Averages over the most recent `limit` reports only, so `rebuffer_count`
    is a per-session average and may be fractional. `startup_ms`
    averages over sessions that actually started — a session that never
    played has no start time to contribute, and counting it as zero would
    make a broken source look instant.
    """
    rows = conn.execute(
        "SELECT started, startup_ms, rebuffer_count, rebuffer_ms, observed_ms "
        "FROM playback_reports WHERE site = ? "
        + ("AND imdb_id = ? " if imdb_id is not None else "")
        + "ORDER BY id DESC LIMIT ?",
        (site, imdb_id, limit) if imdb_id is not None else (site, limit),
    ).fetchall()

    if not rows:
        return None

    started_rows = [row for row in rows if row["started"]]
    startups = [
        row["startup_ms"] for row in started_rows if row["startup_ms"] is not None
    ]

    return {
        "sample_size": len(rows),
        "started": bool(started_rows),
        "startup_ms": round(sum(startups) / len(startups)) if startups else None,
        # Kept fractional: one stall across five sessions is 0.2, and
        # rounding that to a whole 0 erased a real measurement, letting the
        # UI report "no rebuffering" for a session set that stalled.
        "rebuffer_count": round(
            sum(row["rebuffer_count"] for row in rows) / len(rows), 2
        ),
        "rebuffer_ms": round(sum(row["rebuffer_ms"] for row in rows) / len(rows)),
        "observed_ms": round(
            sum(row["observed_ms"] for row in rows) / len(rows)
        ),
    }

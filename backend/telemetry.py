"""Playback evidence reported by real viewers, turned into ranking input.

The streaming sites gate their streams against automated sessions, so this
app cannot measure playback server-side (see docs/Decisions.md). What it
*can* do is accept measurements from the viewer's own browser, where the
stream plays normally — the approach real streaming platforms use for
quality-of-experience monitoring.

Two rules keep this honest, and both are enforced here rather than left to
callers:

1. **A handful of sessions is not evidence.** Below MIN_SAMPLE_SIZE we
   report nothing and the source scores neutrally, rather than ranking on
   one unlucky evening's wifi.
2. **Site-wide data is never presented as title-specific.** When there
   aren't enough reports for this exact title we fall back to the site's
   overall record, but `scope` says so, and the UI shows the difference.
"""
from db.store import playback_stats
from scraper.playback import PlaybackMetrics
from scraper.site_search import domain_of

# Enough sessions to be worth acting on, low enough to be reachable for a
# personal app. Raise it if rankings start looking jumpy.
MIN_SAMPLE_SIZE = 3


def metrics_for(conn, site: str, imdb_id: str | None) -> PlaybackMetrics | None:
    """Reported playback for `site`, preferring evidence about `imdb_id`.

    Returns None when there isn't enough to justify a claim.
    """
    stats, scope = None, "site"

    if imdb_id:
        title_stats = playback_stats(conn, site=site, imdb_id=imdb_id)
        if title_stats and title_stats["sample_size"] >= MIN_SAMPLE_SIZE:
            stats, scope = title_stats, "title"

    if stats is None:
        stats = playback_stats(conn, site=site)

    if stats is None or stats["sample_size"] < MIN_SAMPLE_SIZE:
        return None

    return PlaybackMetrics(
        status="measured",
        started=stats["started"],
        startup_ms=stats["startup_ms"],
        rebuffer_count=stats["rebuffer_count"],
        rebuffer_ms=stats["rebuffer_ms"],
        observed_ms=stats["observed_ms"],
        provenance="reported",
        sample_size=stats["sample_size"],
        scope=scope,
    )


def annotate_reported_playback(conn, candidates: list) -> list:
    """Fill in playback from reported sessions, best-effort.

    Only fills candidates that don't already carry a measurement: a probe
    watched that exact stream itself, which is stronger evidence than an
    average over other people's sessions. Cheap (a bounded local query), so
    unlike probing this runs on every search rather than behind a flag.
    """
    for candidate in candidates:
        if candidate.playback is not None:
            continue
        metrics = metrics_for(conn, domain_of(candidate.url), candidate.imdb_id)
        if metrics is not None:
            candidate.playback = metrics
    return candidates

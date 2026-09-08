"""POST /api/search — resolve a title to a streaming source.

Flow: parse FMHY's curated video directory (cached), score its sites, pick
the best one, persist the query with the chosen source, and return that
source plus the updated search history.

FMHY lists sites, not per-title links, so `top_source.url` is the site to
watch on — not a deep link to the title. Per-title resolution is task S2.
"""
import requests
from flask import Blueprint, current_app, jsonify, request

import scoring
import scraper
import telemetry
from db.store import add_search, list_searches

search_bp = Blueprint("search", __name__, url_prefix="/api")


@search_bp.post("/search")
def search():
    data = request.get_json(silent=True)
    query = (data or {}).get("query", "")
    query = query.strip() if isinstance(query, str) else ""

    if not query:
        return jsonify({"error": "query is required"}), 400

    try:
        candidates = scraper.get_candidates(query)
        # Task S3: check whether the strongest candidates actually have this
        # title. This is the only ranking input that depends on the query, so
        # without it every search returns the same winner (see
        # docs/Decisions.md). Off by default — see create_app.
        if current_app.config.get("PROBE_AVAILABILITY"):
            candidates = scraper.annotate_availability(candidates)
        # Task S4: for the sources that do have the title, measure how the
        # stream actually plays. Only measured results affect ranking —
        # anything untested stays neutral (see scoring/__init__.py).
        if current_app.config.get("PROBE_PLAYBACK"):
            candidates = scraper.annotate_playback(candidates)
        # Real playback measured in viewers' own browsers (telemetry.py).
        # A cheap local read, so unlike probing it always runs — it is the
        # only playback evidence this app can actually collect.
        candidates = telemetry.annotate_reported_playback(
            current_app.config["DB_CONN"], candidates
        )
        best = scoring.pick_best(candidates)
    except requests.RequestException:
        return jsonify({"error": "could not reach the FMHY directory"}), 502
    except ValueError:
        return jsonify({"error": "no streaming sources found"}), 502

    # FMHY's top pick isn't necessarily one we can link straight into for
    # this title, so offer both: the best site overall, and the best site
    # we can open on the searched title. Often they differ.
    linkable = [candidate for candidate in candidates if candidate.is_deep_link]
    best_deep_link = scoring.pick_best(linkable) if linkable else None

    conn = current_app.config["DB_CONN"]
    saved = add_search(
        conn,
        query=query,
        matched_title=best.candidate.matched_title,
        source=best.candidate.url,
        score=best.total_score,
    )

    return (
        jsonify(
            {
                "search": dict(saved),
                "matched_title": best.candidate.matched_title,
                "year": best.candidate.year,
                "imdb_id": best.candidate.imdb_id,
                "top_source": _serialize(best),
                "best_deep_link": (
                    _serialize(best_deep_link) if best_deep_link else None
                ),
                "history": [dict(row) for row in list_searches(conn)],
            }
        ),
        201,
    )


def _serialize_playback(playback) -> dict | None:
    """Expose measured playback, or None when it wasn't measured.

    None is deliberate: the client must be able to tell "we watched this and
    it played well" apart from "we never watched it", and must never render
    the second as the first.
    """
    if playback is None or playback.status != "measured":
        return None
    return {
        "status": playback.status,
        "started": playback.started,
        "startup_ms": playback.startup_ms,
        "rebuffer_count": playback.rebuffer_count,
        "rebuffer_ms": playback.rebuffer_ms,
        "observed_ms": playback.observed_ms,
        "provenance": playback.provenance,
        "sample_size": playback.sample_size,
        "scope": playback.scope,
    }


def _serialize(best: scoring.ScoreResult) -> dict:
    return {
        "url": best.candidate.url,
        "site_name": best.candidate.site_name,
        "is_deep_link": best.candidate.is_deep_link,
        "link_kind": best.candidate.link_kind,
        "subtitle_status": best.candidate.subtitle_status,
        "availability": best.candidate.availability,
        "result_count": best.candidate.result_count,
        "playback": _serialize_playback(best.candidate.playback),
        "rank": best.candidate.rank,
        "starred": best.candidate.starred,
        "total_score": best.total_score,
        "scores": {
            "reliability": best.reliability_score,
            "subtitle": best.subtitle_score,
            "latency": best.latency_score,
        },
    }

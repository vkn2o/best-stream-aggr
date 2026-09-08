"""POST /api/playback-report — real playback measurements from a viewer.

The companion to `clients/streamfinder-qoe.user.js`. The streaming sites
gate their streams against automated sessions, so this app cannot measure
playback itself; instead the viewer's own browser — where the stream plays
normally — reports what it saw, and those numbers drive ranking
(see telemetry.py and docs/Decisions.md).

Everything arriving here was produced by a script running on a third-party
page, which makes it the least trustworthy input in the app. Each field is
validated and the whole report rejected on anything unexpected: unlike a
malformed search, a bad row here would persist and quietly become a
confident wrong recommendation later (docs/Constraints.md #2).
"""
from flask import Blueprint, current_app, jsonify, request

from db.store import add_playback_report
from scraper.tmdb_lookup import MEDIA_TYPES, find_imdb_id

playback_report_bp = Blueprint("playback_report", __name__, url_prefix="/api")

_MAX_SITE_LENGTH = 253  # a hostname can't be longer


@playback_report_bp.post("/playback-report")
def playback_report():
    report = _validated(request.get_json(silent=True))
    if report is None:
        return jsonify({"error": "invalid playback report"}), 400

    add_playback_report(current_app.config["DB_CONN"], **report)
    return jsonify({"stored": True}), 201


def _validated(payload) -> dict | None:
    """Return a clean report, or None if anything about it is off."""
    if not isinstance(payload, dict):
        return None

    site = payload.get("site")
    if not isinstance(site, str) or not site.strip():
        return None
    if len(site) > _MAX_SITE_LENGTH:
        return None

    imdb_id = payload.get("imdb_id")
    if imdb_id is not None and not isinstance(imdb_id, str):
        return None

    # A player page names its title with a TMDB id in the URL and carries no
    # IMDb id at all, so the userscript sends that reference instead and it
    # is mapped back here. Both halves or neither: half a reference is not
    # something the userscript sends, so it is treated as unexpected.
    title_ref = _validated_title_ref(payload)
    if title_ref is False:
        return None
    if not imdb_id and title_ref is not None:
        imdb_id = find_imdb_id(*title_ref)

    started = payload.get("started")
    if not isinstance(started, bool):
        return None

    startup_ms = payload.get("startup_ms")
    if startup_ms is not None and not _is_count(startup_ms):
        return None

    rebuffer_count = payload.get("rebuffer_count")
    rebuffer_ms = payload.get("rebuffer_ms")
    observed_ms = payload.get("observed_ms")
    if not all(_is_count(value) for value in (rebuffer_count, rebuffer_ms)):
        return None
    # A session with no duration measured nothing.
    if not _is_count(observed_ms) or observed_ms <= 0:
        return None

    return {
        "site": site.strip().lower(),
        "imdb_id": imdb_id or None,
        "started": started,
        "startup_ms": startup_ms,
        "rebuffer_count": rebuffer_count,
        "rebuffer_ms": rebuffer_ms,
        "observed_ms": observed_ms,
    }


def _validated_title_ref(payload) -> tuple[int, str] | None | bool:
    """The report's TMDB reference: the pair, None if absent, False if bad."""
    tmdb_id = payload.get("tmdb_id")
    media_type = payload.get("media_type")

    if tmdb_id is None and media_type is None:
        return None
    if not _is_count(tmdb_id) or tmdb_id <= 0:
        return False
    if media_type not in MEDIA_TYPES:
        return False

    return tmdb_id, media_type


def _is_count(value) -> bool:
    """A non-negative whole number — and not a bool wearing an int's clothes."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0

"""Flask app factory for the movie/TV search aggregator backend."""
import os
import sqlite3

from flask import Flask, jsonify
from flask_cors import CORS

from db.store import init_db
from routes.history import history_bp
from routes.playback_report import playback_report_bp
from routes.search import search_bp
from routes.suggestions import suggestions_bp

# Only the frontend's known dev origins — never "*". The app has no
# authentication, but an allowlist still stops an arbitrary third-party
# page from silently proxying a visitor's requests through their browser.
# The Vite dev server's own proxy (see frontend/vite.config.js) doesn't
# need this — same-origin requests are never subject to CORS — but any
# other origin serving the frontend (a different dev port, a built
# production bundle) does. Found missing during full-stack integration
# testing: a direct cross-origin fetch failed with a bare "Failed to
# fetch", with nothing in the response to say it was CORS.
_ALLOWED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

# Origins the playback-report userscript runs on. It posts from the
# streaming site's own page, which is cross-origin to this API, so those
# origins need to be allowed explicitly. Still an allowlist, never "*"
# (docs/Constraints.md #7) — keep this in step with the userscript's
# @match list in clients/streamfinder-qoe.user.js.
_PLAYER_ORIGINS = ["https://flixer.gd"]


def create_app(
    db_path: str = "app.db",
    probe_availability: bool = False,
    probe_playback: bool = False,
) -> Flask:
    """Build the app.

    `probe_availability` turns on the task-S3 per-title availability check
    (see scraper/availability.py). It defaults to **off** because it renders
    pages in a headless browser: that costs seconds per search and needs
    Playwright installed, so tests and any embedding code opt in explicitly
    rather than paying for it by accident. The dev server below turns it on.

    `probe_playback` adds the task-S4 measurement of how the stream actually
    plays (scraper/playback.py). It is much more expensive again — it opens
    the player and watches it — so it is off by default too. It only ever
    measures sources the title is *confirmed available* on, so it implies
    `probe_availability`: enabling playback alone would have no candidates
    to measure, which would silently do nothing.
    """
    app = Flask(__name__)
    CORS(app, origins=_ALLOWED_ORIGINS + _PLAYER_ORIGINS)
    app.config["PROBE_AVAILABILITY"] = probe_availability or probe_playback
    app.config["PROBE_PLAYBACK"] = probe_playback

    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    app.config["DB_CONN"] = conn

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    app.register_blueprint(search_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(suggestions_bp)
    app.register_blueprint(playback_report_bp)

    return app


if __name__ == "__main__":
    # Availability probing is on for the dev server (set STREAM_FINDER_PROBE=0
    # to turn it off — searches get much faster, but go back to returning the
    # same top sites for every title).
    #
    # Playback measurement is opt-in (STREAM_FINDER_PLAYBACK=1): it watches
    # the stream for ~10s per source, which pushes a search past a minute.
    create_app(
        probe_availability=os.environ.get("STREAM_FINDER_PROBE", "1") != "0",
        probe_playback=os.environ.get("STREAM_FINDER_PLAYBACK", "0") == "1",
    ).run(debug=True)

"""GET /history — returns past searches, newest first."""
from flask import Blueprint, current_app, jsonify

from db.store import list_searches

history_bp = Blueprint("history", __name__, url_prefix="/api")


@history_bp.get("/history")
def history():
    conn = current_app.config["DB_CONN"]
    rows = list_searches(conn)
    return jsonify([dict(row) for row in rows]), 200

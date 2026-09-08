"""GET /api/suggestions — live title suggestions for the search box.

A thin wrapper over scraper.get_suggestions (IMDb's suggestion endpoint,
the same one title resolution in /api/search already uses — no separate
lookup or image system). Unlike /api/search, this endpoint backs a
type-ahead dropdown: it must never surface an error to the client, so any
problem (query too short, IMDb down, an unexpected response shape)
degrades to an empty suggestion list with a 200, not a 4xx/5xx.
"""
from flask import Blueprint, jsonify, request

import scraper

suggestions_bp = Blueprint("suggestions", __name__, url_prefix="/api")

_MIN_QUERY_LENGTH = 2
_MAX_SUGGESTIONS = 5


@suggestions_bp.get("/suggestions")
def suggestions():
    query = (request.args.get("q") or "").strip()

    if len(query) < _MIN_QUERY_LENGTH:
        return jsonify({"suggestions": []}), 200

    matches = scraper.get_suggestions(query, limit=_MAX_SUGGESTIONS)

    return (
        jsonify({"suggestions": [_serialize(match) for match in matches]}),
        200,
    )


def _serialize(match) -> dict:
    return {
        "imdb_id": match.imdb_id,
        "title": match.title,
        "year": match.year,
        "kind": match.kind,
        "image_url": match.image_url,
    }

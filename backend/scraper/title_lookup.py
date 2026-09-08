"""Resolve a raw search query to a real movie/TV title.

Uses IMDb's public suggestion endpoint — the same one that powers the
search box on imdb.com. It needs no API key, returns canonical title, year,
type and IMDb id, and is fast enough to call per search.

This is what makes a search title-aware: FMHY gives us ranked *sites*, and
this gives us the *title* to look for on them.
"""
from dataclasses import dataclass
from urllib.parse import quote

import requests

_SUGGESTION_BASE = "https://v2.sg.media-imdb.com/suggestion"
_REQUEST_TIMEOUT_SECONDS = 10

# IMDb mixes people and industry records into results; only these `qid`
# values are things you can actually watch.
_WATCHABLE_KINDS = {
    "movie",
    "tvSeries",
    "tvMiniSeries",
    "tvMovie",
    "tvSpecial",
    "video",
    "short",
}


@dataclass
class ResolvedTitle:
    """A query resolved to a canonical IMDb title."""

    imdb_id: str
    title: str
    year: int | None
    kind: str


@dataclass
class Suggestion:
    """One live autocomplete suggestion for a partially-typed query.

    `image_url` is the poster IMDb's suggestion endpoint already returns
    alongside the title — there's no separate image lookup to build or
    maintain, and no image at all is a normal, expected case (many
    industry/franchise-style entries have none), not a failure.
    """

    imdb_id: str
    title: str
    year: int | None
    kind: str
    image_url: str | None


def suggestion_url(query: str) -> str:
    """Build the suggestion endpoint URL for `query`.

    The endpoint is sharded by the query's first letter.
    """
    normalized = query.strip().lower()
    letter = next((c for c in normalized if c.isalnum()), "x")
    return f"{_SUGGESTION_BASE}/{letter}/{quote(normalized)}.json"


def fetch_suggestions(query: str) -> dict:
    """Fetch raw suggestion results for `query`."""
    response = requests.get(
        suggestion_url(query), timeout=_REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    return response.json()


def resolve_title(query: str) -> ResolvedTitle | None:
    """Return the best watchable match for `query`, or None if there is none."""
    matches = resolve_suggestions(query, limit=1)
    if not matches:
        return None
    best = matches[0]
    return ResolvedTitle(
        imdb_id=best.imdb_id, title=best.title, year=best.year, kind=best.kind
    )


def resolve_suggestions(query: str, limit: int = 5) -> list[Suggestion]:
    """Return up to `limit` watchable matches for `query`, best first.

    IMDb's response shape isn't a contract this app controls, so every
    layer of it is treated as untrusted: a non-dict payload, a missing or
    non-list "d", or a non-dict entry all degrade to "no match(es)" rather
    than raising — the same way an unreachable IMDb already does (see
    docs/Decisions.md). A malformed entry is skipped, not fatal to the
    whole lookup, so one bad entry can't hide a good one later in the list.
    """
    payload = fetch_suggestions(query)
    entries = payload.get("d", []) if isinstance(payload, dict) else []
    if not isinstance(entries, list):
        return []

    suggestions: list[Suggestion] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        imdb_id = entry.get("id", "")
        if not isinstance(imdb_id, str) or not imdb_id.startswith("tt"):
            continue
        if entry.get("qid") not in _WATCHABLE_KINDS:
            continue

        image = entry.get("i")
        image_url = image.get("imageUrl") if isinstance(image, dict) else None

        suggestions.append(
            Suggestion(
                imdb_id=imdb_id,
                title=entry.get("l", query),
                year=entry.get("y"),
                kind=entry["qid"],
                image_url=image_url if isinstance(image_url, str) else None,
            )
        )
        if len(suggestions) >= limit:
            break

    return suggestions

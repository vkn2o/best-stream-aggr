"""Map an IMDb id to a TMDB id, so we can build direct player links.

The streaming sites' player routes key on **TMDB** ids
(`/watch/movie/{tmdbId}`), while this app resolves **IMDb** ids via
`title_lookup.py`. This module bridges the two using TMDB's documented
`/find/{external_id}` endpoint.

Entirely optional, by design. Without a `TMDB_API_KEY` — which is the
default state, since obtaining one is a manual step — every lookup returns
None and `site_search.py` falls back to the search links the app has always
built. Nothing degrades except link precision, and nothing here ever raises
into a request: a network failure, a non-JSON body or an unexpected shape
all come back as None (docs/Constraints.md #2).

Results are cached for a day, negative results included: an IMDb->TMDB
mapping is effectively immutable, so re-asking is pure waste.
"""
import logging
import os
import time
from dataclasses import dataclass

import requests

_logger = logging.getLogger(__name__)

_FIND_URL = "https://api.themoviedb.org/3/find/{imdb_id}"
_EXTERNAL_IDS_URL = (
    "https://api.themoviedb.org/3/{media_type}/{tmdb_id}/external_ids"
)
MEDIA_TYPES = ("movie", "tv")
_API_KEY_ENV = "TMDB_API_KEY"
_REQUEST_TIMEOUT_SECONDS = 10
CACHE_TTL_SECONDS = 24 * 60 * 60

_cache: dict[str, tuple[float, "TmdbMatch | None"]] = {}
# Keyed by (tmdb_id, media_type): the two namespaces overlap, and TMDB
# movie 603 is not TMDB series 603.
_imdb_cache: dict[tuple[int, str], tuple[float, str | None]] = {}


@dataclass
class TmdbMatch:
    """A title identified in TMDB's namespace."""

    tmdb_id: int
    media_type: str  # "movie" | "tv"


def api_key() -> str | None:
    """The configured TMDB key, or None when the feature is switched off."""
    key = (os.environ.get(_API_KEY_ENV) or "").strip()
    return key or None


def find_tmdb_id(imdb_id: str) -> TmdbMatch | None:
    """Return the TMDB id for `imdb_id`, or None if it can't be determined.

    Never raises: the caller treats "no answer" and "couldn't ask" the same
    way, because both mean the same thing for link building.
    """
    if not imdb_id:
        return None

    cached = _cache.get(imdb_id)
    if cached is not None and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    key = api_key()
    if key is None:
        # Not configured — don't cache this, so setting a key mid-session
        # starts working without a restart.
        return None

    try:
        payload = _fetch_find(imdb_id, key)
    except (requests.RequestException, ValueError):
        _logger.warning("TMDB lookup failed for %s", imdb_id, exc_info=True)
        return None

    match = _parse_find(payload)
    _cache[imdb_id] = (time.monotonic(), match)
    return match


def find_imdb_id(tmdb_id: int, media_type: str) -> str | None:
    """Return the IMDb id for a TMDB title, or None if it can't be determined.

    The reverse of `find_tmdb_id`, and the reason it exists: the player
    pages a viewer actually watches carry a TMDB id in their URL and no
    IMDb id anywhere, so a playback report can only name the title it
    watched if that id is mapped back (see routes/playback_report.py).

    Never raises, and returns None without a key — a report that cannot be
    tied to a title is still stored as site-wide evidence.
    """
    if media_type not in MEDIA_TYPES:
        return None
    if not isinstance(tmdb_id, int) or isinstance(tmdb_id, bool) or tmdb_id <= 0:
        return None

    cache_key = (tmdb_id, media_type)
    cached = _imdb_cache.get(cache_key)
    if cached is not None and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    key = api_key()
    if key is None:
        # Not cached, so setting a key mid-session starts working at once.
        return None

    try:
        payload = _fetch_external_ids(tmdb_id, media_type, key)
    except (requests.RequestException, ValueError):
        _logger.warning(
            "TMDB external-ids lookup failed for %s %s",
            media_type,
            tmdb_id,
            exc_info=True,
        )
        return None

    imdb_id = _parse_external_ids(payload)
    _imdb_cache[cache_key] = (time.monotonic(), imdb_id)
    return imdb_id


def clear_cache() -> None:
    """Drop cached mappings (used by tests)."""
    _cache.clear()
    _imdb_cache.clear()


def _fetch_find(imdb_id: str, api_key: str) -> dict:
    """Ask TMDB which of its titles corresponds to this IMDb id."""
    response = requests.get(
        _FIND_URL.format(imdb_id=imdb_id),
        params={"api_key": api_key, "external_source": "imdb_id"},
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def _parse_find(payload) -> TmdbMatch | None:
    """Read a TMDB /find response, treating every layer as untrusted.

    Movies are preferred over TV when both match, matching how
    `title_lookup` picks the first watchable result: a query that resolves
    to both is overwhelmingly a film with a same-named series.
    """
    if not isinstance(payload, dict):
        return None

    for key, media_type in (("movie_results", "movie"), ("tv_results", "tv")):
        results = payload.get(key)
        if not isinstance(results, list):
            continue
        for entry in results:
            if not isinstance(entry, dict):
                continue
            tmdb_id = entry.get("id")
            # bool is a subclass of int, so exclude it explicitly.
            if not isinstance(tmdb_id, int) or isinstance(tmdb_id, bool):
                continue
            return TmdbMatch(tmdb_id=tmdb_id, media_type=media_type)

    return None


def _fetch_external_ids(tmdb_id: int, media_type: str, api_key: str) -> dict:
    """Ask TMDB which external ids one of its titles carries."""
    response = requests.get(
        _EXTERNAL_IDS_URL.format(media_type=media_type, tmdb_id=tmdb_id),
        params={"api_key": api_key},
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def _parse_external_ids(payload) -> str | None:
    """Read an IMDb id out of a TMDB external-ids response.

    The `tt` prefix is checked rather than assumed: the same field shape
    carries `nm...` person ids elsewhere in TMDB's API, and storing one as
    a title id would silently mis-attribute every session reported for it.
    """
    if not isinstance(payload, dict):
        return None

    imdb_id = payload.get("imdb_id")
    if not isinstance(imdb_id, str) or not imdb_id.startswith("tt"):
        return None

    return imdb_id

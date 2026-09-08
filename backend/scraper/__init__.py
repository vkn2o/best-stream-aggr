"""Scraper interface.

A search runs two lookups: FMHY's ranked site list (fmhy_source_list) and
IMDb's title resolution (title_lookup). Together they answer "which sites
are best" and "what exactly is the user looking for", and site_search turns
that pair into a link per site.

FMHY is required — without it there are no candidates. IMDb is an
enhancement: if it's unreachable or finds nothing, searches still work
using the raw query, just without a canonical title/year.
"""
from dataclasses import dataclass

import requests

from scraper.availability import DEFAULT_PROBE_LIMIT, probe_availability
from scraper.playback import (
    DEFAULT_PLAYBACK_LIMIT,
    PlaybackMetrics,
    probe_playback,
)
from scraper.fmhy_source_list import get_streaming_sites
from scraper.site_search import build_site_links
from scraper.title_lookup import ResolvedTitle, Suggestion, resolve_suggestions, resolve_title
from scraper.tmdb_lookup import TmdbMatch, find_tmdb_id


@dataclass
class Candidate:
    """One candidate streaming source for a searched title.

    `rank`/`starred` come from FMHY's curation. `matched_title`, `year` and
    `imdb_id` are None when IMDb couldn't resolve the query. `url` is a
    deep link into the site's search when we've verified that site's search
    route (`is_deep_link`), otherwise the site's home page.

    `availability` is the only *title-dependent* field here: "available" /
    "unavailable" once a site has actually been rendered and checked for
    this specific title (task S3), "unknown" when it wasn't or couldn't be
    probed. `result_count` is how many matches that site showed, when known.
    """

    title: str
    url: str
    site_name: str
    is_deep_link: bool = False
    subtitle_status: str = "unknown"
    rank: int = 0
    starred: bool = False
    matched_title: str | None = None
    year: int | None = None
    imdb_id: str | None = None
    availability: str = "unknown"
    result_count: int | None = None
    # "title" | "search" | "home" — how precisely this url points at the
    # searched title. See site_search.SiteLink.
    link_kind: str = "home"
    # Task S4: what playback actually did when we watched it, or None/
    # "unknown" when it wasn't measured. Never inferred from availability —
    # a site can have the title and still stall constantly.
    playback: PlaybackMetrics | None = None


def get_candidates(query: str) -> list[Candidate]:
    """Return FMHY's sites as candidates for `query`, best first."""
    sites = get_streaming_sites()
    resolved = _resolve_quietly(query)
    search_for = resolved or ResolvedTitle(
        imdb_id="", title=query, year=None, kind=""
    )
    # The sites' player routes key on TMDB ids, not IMDb ones. Optional:
    # without a configured key this is None and links stay as they were.
    tmdb = find_tmdb_id(resolved.imdb_id) if resolved else None

    return [
        Candidate(
            title=search_for.title,
            url=link.url,
            site_name=link.site_name,
            is_deep_link=link.is_deep_link,
            subtitle_status=link.subtitle_status,
            rank=link.rank,
            starred=link.starred,
            matched_title=resolved.title if resolved else None,
            year=resolved.year if resolved else None,
            imdb_id=resolved.imdb_id if resolved else None,
            link_kind=link.link_kind,
        )
        for link in build_site_links(sites, search_for, tmdb=tmdb)
    ]


def annotate_availability(
    candidates: list[Candidate], limit: int = DEFAULT_PROBE_LIMIT
) -> list[Candidate]:
    """Fill in each candidate's per-title availability, best candidates first.

    Renders a few of the strongest candidates to see whether they actually
    have this title (task S3). Candidates that can't be probed keep
    `availability="unknown"` and are scored neutrally, so this only ever
    adds information — a probe that finds nothing leaves ranking exactly as
    it was.
    """
    results = probe_availability(candidates, limit=limit)
    for candidate in candidates:
        result = results.get(candidate.url)
        if result is not None:
            candidate.availability = result.status
            candidate.result_count = result.result_count
    return candidates


def annotate_playback(
    candidates: list[Candidate], limit: int = DEFAULT_PLAYBACK_LIMIT
) -> list[Candidate]:
    """Measure playback quality for the best few candidates (task S4).

    Only opens sources the title is confirmed available on, so it never
    wastes a browser session on a site that doesn't have it. Candidates that
    weren't or couldn't be measured keep `playback=None` and are scored
    neutrally — this only ever adds evidence.
    """
    results = probe_playback(candidates, limit=limit)
    for candidate in candidates:
        metrics = results.get(candidate.url)
        if metrics is not None:
            candidate.playback = metrics
    return candidates


def get_suggestions(query: str, limit: int = 5) -> list[Suggestion]:
    """Return up to `limit` live autocomplete suggestions for `query`.

    Autocomplete is a convenience layered on the same IMDb lookup as
    `get_candidates` — it must degrade to "no suggestions" rather than
    fail the request, the same reasoning as `_resolve_quietly` below, but
    also covering a malformed (non-JSON) response body, which a dropdown
    that types as the user is still typing is more likely to hit than a
    single per-submit lookup.
    """
    try:
        return resolve_suggestions(query, limit=limit)
    except (requests.RequestException, ValueError):
        return []


def refresh_sources() -> int:
    """Re-fetch FMHY's directory, bypassing the cache; return how many sites."""
    return len(get_streaming_sites(force_refresh=True))


def _resolve_quietly(query: str) -> ResolvedTitle | None:
    """Resolve `query` via IMDb, treating any failure as "unresolved".

    A search is still useful without a canonical title, so an IMDb outage
    must not fail the whole request the way an FMHY outage does.
    """
    try:
        return resolve_title(query)
    except requests.RequestException:
        return None

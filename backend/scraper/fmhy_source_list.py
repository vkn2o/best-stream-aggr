"""Stage A: parse FMHY's video directory into a ranked list of sites.

Reads FMHY's markdown source rather than scraping the rendered site: the
rendered wiki is a JS-driven SPA, while `docs/video.md` in the FMHY repo is
the same content in a stable, parseable form (see docs/Decisions.md).

FMHY's own ordering *is* the ranking — the list is hand-curated with the
best entries first and the strongest recommendations marked with a star —
so position in the document is the ranking signal, no scoring needed here.
"""
import logging
import re
import time
from dataclasses import dataclass

import requests

_logger = logging.getLogger(__name__)

# FMHY's video directory in markdown form (the source the wiki renders from).
FMHY_VIDEO_MARKDOWN_URL = (
    "https://raw.githubusercontent.com/fmhy/edit/main/docs/video.md"
)

# FMHY's directory changes on the order of days, so an hour-long cache keeps
# per-search latency down without serving a stale list.
CACHE_TTL_SECONDS = 60 * 60
_REQUEST_TIMEOUT_SECONDS = 15

_cache: tuple[float, list["StreamingSite"]] | None = None

# The top-level section holding actual streaming sites. Other "# ►" sections
# (Streaming Apps, Download Sites, Torrent Sites, ...) aren't watch-in-browser
# sources, so they're out of scope for this app.
_STREAMING_SITES_HEADING = "# ► Streaming Sites"

_TOP_LEVEL_HEADING = re.compile(r"^# ► (.+)$")
_SUBSECTION_HEADING = re.compile(r"^## ▷ (.+)$")
_BULLET = re.compile(r"^\* (.+)$")
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")

# Links to the wiki itself or to the FMHY repo are cross-references and
# grading pages, not streaming sites.
_CROSS_REFERENCE_DOMAINS = ("reddit.com", "github.com")


@dataclass
class StreamingSite:
    """One streaming site listed in FMHY's video directory."""

    name: str
    url: str
    rank: int
    starred: bool
    section: str


def parse_streaming_sites(markdown: str) -> list[StreamingSite]:
    """Extract streaming sites from FMHY's video markdown, in list order."""
    sites: list[StreamingSite] = []
    in_streaming_sites = False
    section = ""

    for line in markdown.splitlines():
        top_level = _TOP_LEVEL_HEADING.match(line)
        if top_level:
            in_streaming_sites = line.strip() == _STREAMING_SITES_HEADING
            section = ""
            continue

        subsection = _SUBSECTION_HEADING.match(line)
        if subsection:
            section = _strip_markdown_link(subsection.group(1)).strip()
            continue

        if not in_streaming_sites:
            continue

        bullet = _BULLET.match(line)
        if not bullet:
            continue

        site = _parse_bullet(bullet.group(1), rank=len(sites) + 1, section=section)
        if site is not None:
            sites.append(site)

    return sites


def rank_sites(sites: list[StreamingSite]) -> list[StreamingSite]:
    """Order sites best-first: starred entries first, then FMHY's own order.

    FMHY stars its strongest recommendations, and those stars appear in
    every subsection — so a plain document-order sort would rank an
    unstarred aggregator above a starred dedicated-server site. Sorting
    starred-first, then by rank, keeps FMHY's intent across sections.
    """
    return sorted(sites, key=lambda site: (not site.starred, site.rank))


def fetch_video_markdown() -> str:
    """Download FMHY's video directory markdown."""
    response = requests.get(
        FMHY_VIDEO_MARKDOWN_URL, timeout=_REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    return response.text


def get_streaming_sites(force_refresh: bool = False) -> list[StreamingSite]:
    """Return FMHY's streaming sites best-first, cached for CACHE_TTL_SECONDS.

    A fetch failure (FMHY down, DNS, timeout) falls back to whatever is
    cached, even if expired, rather than failing the request: FMHY's
    directory changes on the order of days, so a stale-by-a-few-hours list
    is still almost certainly correct, and is strictly more useful than a
    hard failure. Only raises when there is truly no cache to fall back on.
    """
    global _cache

    if not force_refresh and _cache is not None:
        cached_at, sites = _cache
        if _now() - cached_at < CACHE_TTL_SECONDS:
            return sites

    try:
        markdown = fetch_video_markdown()
    except requests.RequestException:
        if _cache is not None:
            _logger.warning(
                "FMHY fetch failed; serving cached list from %.0fs ago",
                _now() - _cache[0],
                exc_info=True,
            )
            return _cache[1]
        raise

    sites = rank_sites(parse_streaming_sites(markdown))
    if not sites:
        # A successful fetch with zero parsed sites almost always means
        # FMHY changed its markdown structure (headings, bullet format)
        # rather than that the directory is genuinely empty — this is the
        # signal to look at fmhy_source_list.py's parsing regexes again.
        _logger.warning(
            "Fetched FMHY markdown but parsed 0 streaming sites — "
            "the page structure may have changed"
        )
    _cache = (_now(), sites)
    return sites


def clear_cache() -> None:
    """Drop the cached site list (used by tests and by a forced refresh)."""
    global _cache
    _cache = None


def _now() -> float:
    return time.monotonic()


def _parse_bullet(text: str, rank: int, section: str) -> StreamingSite | None:
    starred = "⭐" in text

    # "**Note** - ..." bullets are section prose, not entries.
    if text.lstrip("⭐↪️ ").startswith("**Note**"):
        return None

    match = _MARKDOWN_LINK.search(text)
    if match is None:
        return None

    name, url = match.group(1).strip(), match.group(2)

    if any(domain in url for domain in _CROSS_REFERENCE_DOMAINS):
        return None

    return StreamingSite(
        name=name, url=url, rank=rank, starred=starred, section=section
    )


def _strip_markdown_link(text: str) -> str:
    """Turn "[Name](url)" into "Name" — some headings are themselves links."""
    match = _MARKDOWN_LINK.fullmatch(text.strip())
    return match.group(1) if match else text

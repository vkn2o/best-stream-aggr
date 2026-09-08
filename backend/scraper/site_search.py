"""Stage B: turn a resolved title into a link on each candidate site.

Originally planned as "scrape each site's search results with
BeautifulSoup". That isn't possible: every top FMHY site renders search
results client-side, so the HTML a request returns contains no results at
all (evidence in docs/Decisions.md). Rather than launch a browser per site
per search, this module links *into* each site's own search for the
resolved title.

The adapter table below holds only routes verified against the live sites.
For anything unverified we link to the site's home page and say so
(`is_deep_link=False`) instead of guessing a path — a guessed route lands
the user on a 404, which is worse than an honest home-page link.
"""
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit, urlunsplit

from scraper.fmhy_source_list import StreamingSite
from scraper.title_lookup import ResolvedTitle
from scraper.tmdb_lookup import TmdbMatch

# domain -> (search path, query parameter name)
# Verified by inspecting each site's route manifest / JS bundle.
_SEARCH_ADAPTERS: dict[str, tuple[str, str]] = {
    "flixer.gd": ("/search", "q"),
    "boomflix.qzz.io": ("/search", "q"),
    "rivestream.app": ("/search", "query"),
}


# domain -> builder(tmdb_id, media_type) -> path into that site's player.
# Read from each site's own published route manifest and then verified
# against the live site, exactly like _SEARCH_ADAPTERS. A route that exists
# in a bundle but doesn't actually render a player is NOT registered:
# boomflix.qzz.io publishes /player/:id but never reaches a video element,
# so it stays on search links (see docs/Decisions.md).
_TITLE_ADAPTERS = {
    "flixer.gd": lambda tmdb_id, media_type: (
        f"/watch/movie/{tmdb_id}"
        if media_type == "movie"
        else f"/watch/tv/{tmdb_id}/1/1"
        if media_type == "tv"
        else None
    ),
}


@dataclass
class SiteLink:
    """Where to watch `title` on one site, and how confident we are in it."""

    site_name: str
    url: str
    is_deep_link: bool
    rank: int
    starred: bool
    # "title"  — straight to the site's player for this title (best)
    # "search" — the site's search results for the title
    # "home"   — the site's front page, nothing title-specific
    link_kind: str = "home"
    # "unknown" until something can actually read the player's subtitle
    # tracks — see module docstring.
    subtitle_status: str = "unknown"


def build_site_link(
    site: StreamingSite, title: ResolvedTitle, tmdb: TmdbMatch | None = None
) -> SiteLink:
    """Build the best available link to `title` on `site`.

    Best to worst: the site's player for this exact title, the site's search
    results for it, the site's home page. A player link needs a TMDB id,
    which is optional (see tmdb_lookup.py) — without one this behaves
    exactly as it always has.
    """
    url = _title_url(site, tmdb)
    link_kind = "title"

    if url is None:
        url = _search_url(site, title)
        link_kind = "search"

    if url is None:
        url, link_kind = site.url, "home"

    return SiteLink(
        site_name=site.name,
        url=url,
        is_deep_link=link_kind != "home",
        rank=site.rank,
        starred=site.starred,
        link_kind=link_kind,
    )


def _title_url(site: StreamingSite, tmdb: TmdbMatch | None) -> str | None:
    """A link into the site's player for this title, if we can build one."""
    if tmdb is None:
        return None
    adapter = _TITLE_ADAPTERS.get(_domain(site.url))
    if adapter is None:
        return None
    path = adapter(tmdb.tmdb_id, tmdb.media_type)
    if path is None:
        # An unrecognised media type — fall back rather than guess a route.
        return None
    return _with_path_and_query(site.url, path, {})


def _search_url(site: StreamingSite, title: ResolvedTitle) -> str | None:
    """A link into the site's own search for this title, if it has one."""
    adapter = _SEARCH_ADAPTERS.get(_domain(site.url))
    if adapter is None:
        return None
    path, parameter = adapter
    return _with_path_and_query(site.url, path, {parameter: title.title})


def build_site_links(
    sites: list[StreamingSite],
    title: ResolvedTitle,
    limit: int | None = None,
    tmdb: TmdbMatch | None = None,
) -> list[SiteLink]:
    """Build links for `sites`, preserving their (already ranked) order."""
    selected = sites if limit is None else sites[:limit]
    return [build_site_link(site, title, tmdb=tmdb) for site in selected]


def domain_of(url: str) -> str:
    """The bare host for `url`, without a leading "www."."""
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


# Kept as the module-internal spelling used throughout this file.
_domain = domain_of


def _with_path_and_query(url: str, path: str, params: dict[str, str]) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, path, urlencode(params), ""))

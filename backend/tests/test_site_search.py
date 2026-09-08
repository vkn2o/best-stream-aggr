"""Tests for scraper/site_search.py — turning a resolved title into links.

The adapter table only contains search routes verified against the live
sites (see docs/Decisions.md); everything else falls back to the site's
home page and is marked as not a deep link, rather than guessing a route
that may 404.
"""
from scraper.fmhy_source_list import StreamingSite
from scraper.site_search import SiteLink, build_site_link, build_site_links
from scraper.title_lookup import ResolvedTitle
from scraper.tmdb_lookup import TmdbMatch

_TITLE = ResolvedTitle(
    imdb_id="tt0133093", title="The Matrix", year=1999, kind="movie"
)


def _site(name: str, url: str, rank: int = 1, starred: bool = True):
    return StreamingSite(
        name=name, url=url, rank=rank, starred=starred, section="Stream Aggregators"
    )


def test_builds_a_deep_search_link_for_a_site_with_a_verified_route():
    link = build_site_link(_site("Flixer", "https://flixer.gd"), _TITLE)

    assert link.url == "https://flixer.gd/search?q=The+Matrix"
    assert link.is_deep_link is True


def test_uses_the_sites_own_query_parameter_name():
    link = build_site_link(_site("Rive", "https://www.rivestream.app/"), _TITLE)

    assert link.url == "https://www.rivestream.app/search?query=The+Matrix"


def test_matches_the_adapter_regardless_of_www_or_trailing_slash():
    with_www = build_site_link(_site("Rive", "https://www.rivestream.app/"), _TITLE)
    without_www = build_site_link(_site("Rive", "https://rivestream.app"), _TITLE)

    assert with_www.is_deep_link is True
    assert without_www.is_deep_link is True


def test_falls_back_to_the_home_page_for_an_unverified_site():
    link = build_site_link(_site("Cinejoy", "https://cinejoy.to/"), _TITLE)

    assert link.url == "https://cinejoy.to/"
    assert link.is_deep_link is False


def test_link_carries_the_site_identity_and_ranking():
    link = build_site_link(
        _site("Flixer", "https://flixer.gd", rank=3, starred=True), _TITLE
    )

    assert isinstance(link, SiteLink)
    assert link.site_name == "Flixer"
    assert link.rank == 3
    assert link.starred is True


def test_reports_subtitle_status_as_unknown():
    # Subtitle tracks live inside the site's player, which is rendered
    # client-side — not knowable without a browser (see docs/Decisions.md).
    link = build_site_link(_site("Flixer", "https://flixer.gd"), _TITLE)

    assert link.subtitle_status == "unknown"


def test_build_site_links_preserves_the_fmhy_ordering():
    sites = [
        _site("Cinejoy", "https://cinejoy.to/", rank=1),
        _site("Flixer", "https://flixer.gd", rank=2),
    ]

    links = build_site_links(sites, _TITLE)

    assert [link.site_name for link in links] == ["Cinejoy", "Flixer"]


def test_build_site_links_can_limit_how_many_sites_it_returns():
    sites = [_site(f"S{i}", f"https://s{i}.test/", rank=i) for i in range(1, 6)]

    links = build_site_links(sites, _TITLE, limit=2)

    assert len(links) == 2


_TV_TITLE = ResolvedTitle(
    imdb_id="tt0903747", title="Breaking Bad", year=2008, kind="tvSeries"
)


class TestTitleLinks:
    """Links straight to a site's player page, not its search results.

    Routes come from each site's own published route manifest and are
    verified against the live site before being registered (the same rule
    as the search adapters). Building one needs a TMDB id, which is
    optional — without it we fall back to the search link.
    """

    _FLIXER = _site("Flixer", "https://flixer.gd")

    def test_builds_a_player_link_for_a_movie(self):
        link = build_site_link(self._FLIXER, _TITLE, tmdb=TmdbMatch(603, "movie"))

        assert link.url == "https://flixer.gd/watch/movie/603"
        assert link.link_kind == "title"
        assert link.is_deep_link is True

    def test_builds_a_player_link_for_a_series_defaulting_to_the_first_episode(self):
        link = build_site_link(
            self._FLIXER, _TV_TITLE, tmdb=TmdbMatch(1396, "tv")
        )

        # There is no "the" episode for a series search, so S1E1 is an
        # explicit, documented starting point rather than a guess.
        assert link.url == "https://flixer.gd/watch/tv/1396/1/1"
        assert link.link_kind == "title"

    def test_a_title_link_is_preferred_over_a_search_link(self):
        with_id = build_site_link(self._FLIXER, _TITLE, tmdb=TmdbMatch(603, "movie"))
        without_id = build_site_link(self._FLIXER, _TITLE)

        assert "/watch/movie/" in with_id.url
        assert "/search" in without_id.url

    def test_falls_back_to_the_search_link_without_a_tmdb_id(self):
        link = build_site_link(self._FLIXER, _TITLE, tmdb=None)

        assert link.url == "https://flixer.gd/search?q=The+Matrix"
        assert link.link_kind == "search"
        assert link.is_deep_link is True

    def test_falls_back_to_the_search_link_for_a_site_with_no_title_route(self):
        # Only sites whose player route has been verified are registered.
        boomflix = _site("BoomFlix", "https://boomflix.qzz.io")

        link = build_site_link(boomflix, _TITLE, tmdb=TmdbMatch(603, "movie"))

        assert link.link_kind == "search"

    def test_falls_back_to_the_home_page_for_a_site_with_no_routes_at_all(self):
        link = build_site_link(
            _site("Cinejoy", "https://cinejoy.to/"), _TITLE, tmdb=TmdbMatch(603, "movie")
        )

        assert link.url == "https://cinejoy.to/"
        assert link.link_kind == "home"
        assert link.is_deep_link is False

    def test_an_unknown_media_type_does_not_produce_a_guessed_route(self):
        link = build_site_link(
            self._FLIXER, _TITLE, tmdb=TmdbMatch(603, "something-else")
        )

        assert link.link_kind == "search"

    def test_build_site_links_passes_the_tmdb_id_through(self):
        links = build_site_links(
            [self._FLIXER], _TITLE, tmdb=TmdbMatch(603, "movie")
        )

        assert links[0].url == "https://flixer.gd/watch/movie/603"

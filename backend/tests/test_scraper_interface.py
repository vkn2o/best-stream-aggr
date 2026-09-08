"""Tests for the scraper package's public interface.

Both network boundaries (the FMHY list and the IMDb title lookup) are
stubbed; the parsing and link-building beneath them run for real and have
their own tests.
"""
import pytest
import requests

import scraper
from scraper import Candidate, get_candidates, refresh_sources
from scraper.fmhy_source_list import StreamingSite
from scraper.title_lookup import ResolvedTitle

_SITES = [
    StreamingSite(
        name="Flixer",
        url="https://flixer.gd",
        rank=1,
        starred=True,
        section="Stream Aggregators",
    ),
    StreamingSite(
        name="Cinejoy",
        url="https://cinejoy.to/",
        rank=2,
        starred=False,
        section="Stream Aggregators",
    ),
]

_RESOLVED = ResolvedTitle(
    imdb_id="tt0133093", title="The Matrix", year=1999, kind="movie"
)


@pytest.fixture
def stub_sites(monkeypatch):
    calls = []

    def fake_get_streaming_sites(force_refresh: bool = False):
        calls.append(force_refresh)
        return _SITES

    monkeypatch.setattr(scraper, "get_streaming_sites", fake_get_streaming_sites)
    return calls


@pytest.fixture
def stub_resolve(monkeypatch):
    def install(result):
        def fake_resolve(query):
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(scraper, "resolve_title", fake_resolve)

    install(_RESOLVED)
    return install


def test_get_candidates_uses_the_resolved_title_for_deep_search_links(
    stub_sites, stub_resolve
):
    [flixer, _] = get_candidates("matrix")

    assert flixer.url == "https://flixer.gd/search?q=The+Matrix"
    assert flixer.is_deep_link is True


def test_get_candidates_reports_the_matched_title_and_year(stub_sites, stub_resolve):
    [flixer, _] = get_candidates("matrix")

    assert flixer.matched_title == "The Matrix"
    assert flixer.year == 1999
    assert flixer.imdb_id == "tt0133093"


def test_get_candidates_links_to_the_home_page_for_unverified_sites(
    stub_sites, stub_resolve
):
    [_, cinejoy] = get_candidates("matrix")

    assert cinejoy.url == "https://cinejoy.to/"
    assert cinejoy.is_deep_link is False


def test_get_candidates_preserves_fmhy_best_first_ordering(stub_sites, stub_resolve):
    candidates = get_candidates("matrix")

    assert [c.site_name for c in candidates] == ["Flixer", "Cinejoy"]
    assert all(isinstance(c, Candidate) for c in candidates)


def test_get_candidates_reports_subtitle_status_as_unknown(stub_sites, stub_resolve):
    [flixer, _] = get_candidates("matrix")

    assert flixer.subtitle_status == "unknown"


def test_get_candidates_falls_back_to_the_raw_query_when_imdb_finds_nothing(
    stub_sites, stub_resolve
):
    stub_resolve(None)

    [flixer, _] = get_candidates("some obscure thing")

    assert flixer.url == "https://flixer.gd/search?q=some+obscure+thing"
    assert flixer.matched_title is None


def test_get_candidates_still_works_when_the_imdb_lookup_fails(
    stub_sites, stub_resolve
):
    stub_resolve(requests.RequestException("imdb down"))

    [flixer, _] = get_candidates("matrix")

    assert flixer.url == "https://flixer.gd/search?q=matrix"
    assert flixer.matched_title is None


def test_refresh_sources_returns_the_number_of_sites_found(stub_sites):
    assert refresh_sources() == 2


def test_refresh_sources_forces_a_cache_refresh(stub_sites):
    refresh_sources()

    assert stub_sites == [True]

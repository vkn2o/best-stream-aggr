"""Tests for scraper/availability.py — task S3, per-title availability.

The Playwright render is the one non-deterministic boundary and is always
stubbed here (`_render_page_text`); the detection logic on top of it runs
for real. No test in this file may launch a browser.

Detection strings come from real rendered pages captured during the S3
feasibility spike — notably that a site echoes the search term back even
when it has zero results, so "the title appears in the page" is NOT a
usable availability signal. The result count is.
"""
import pytest

from scraper import availability
from scraper.availability import (
    AvailabilityResult,
    detect_availability,
    probe_availability,
)
from scraper.site_search import SiteLink

# Real captured text (trimmed) from flixer.gd search pages.
_FLIXER_HIT = (
    'Home\nMovies\nTV Shows\nMy List\nActors\nLive Sports\nSign In\nSearch\n'
    'Results for:\n"The Matrix"\n\n59 results found\n\nNo more results'
)
_FLIXER_ONE = (
    'Home\nMovies\nSearch\nResults for:\n"New Amsterdam"\n\n6 results found'
)
_FLIXER_MISS = (
    'Home\nMovies\nTV Shows\nSearch\nResults for:\n"Qwzxjkl Notreal"\n\n'
    '0 results found\n\nNo results found\n\nWe couldn\'t find any content '
    'matching your search criteria.'
)


def _link(url="https://flixer.gd/search?q=The+Matrix", name="Flixer", **kw):
    defaults = dict(site_name=name, url=url, is_deep_link=True, rank=1, starred=True)
    defaults.update(kw)
    return SiteLink(**defaults)


class TestDetectAvailability:
    def test_reports_available_with_the_result_count_when_a_site_has_hits(self):
        assert detect_availability("flixer.gd", _FLIXER_HIT) == AvailabilityResult(
            status="available", result_count=59
        )

    def test_a_single_digit_result_count_still_counts_as_available(self):
        assert detect_availability("flixer.gd", _FLIXER_ONE) == AvailabilityResult(
            status="available", result_count=6
        )

    def test_reports_unavailable_when_the_site_returns_zero_results(self):
        assert detect_availability("flixer.gd", _FLIXER_MISS) == AvailabilityResult(
            status="unavailable", result_count=0
        )

    def test_echoed_search_term_alone_does_not_count_as_a_hit(self):
        # Regression guard for the naive detector: the miss page contains the
        # searched title verbatim ("Qwzxjkl Notreal"), so any substring-based
        # check would wrongly call this available.
        assert "Qwzxjkl Notreal" in _FLIXER_MISS
        assert detect_availability("flixer.gd", _FLIXER_MISS).status == "unavailable"

    def test_unknown_for_a_domain_with_no_verified_detector(self):
        assert detect_availability("rivestream.app", "anything") == AvailabilityResult(
            status="unknown", result_count=None
        )

    def test_unknown_when_the_page_rendered_empty(self):
        # Rive/Boomflix render an empty or shell-only body headlessly.
        assert detect_availability("flixer.gd", "").status == "unknown"

    def test_unknown_when_the_page_lacks_the_expected_result_marker(self):
        # A layout change on the site must degrade to "unknown", never to a
        # confident wrong answer.
        assert (
            detect_availability("flixer.gd", "Home\nMovies\nSomething else").status
            == "unknown"
        )


class TestProbeAvailability:
    @pytest.fixture
    def stub_render(self, monkeypatch):
        """Stub the one Playwright boundary, recording every URL rendered."""

        def install(mapping, default=None):
            def fake_render(url, timeout_ms):
                result = mapping.get(url, default)
                if isinstance(result, Exception):
                    raise result
                install.rendered.append(url)
                return result

            monkeypatch.setattr(availability, "_render_page_text", fake_render)

        install.rendered = []
        return install

    def test_probes_only_links_whose_domain_has_a_verified_detector(
        self, stub_render
    ):
        stub_render({}, default=_FLIXER_HIT)

        links = [
            _link(url="https://cinejoy.to/", name="Cinejoy", is_deep_link=False),
            _link(),
            _link(url="https://www.rivestream.app/search?query=x", name="Rive"),
        ]
        results = probe_availability(links)

        assert stub_render.rendered == ["https://flixer.gd/search?q=The+Matrix"]
        assert results["https://flixer.gd/search?q=The+Matrix"].status == "available"
        # Un-probeable sites simply aren't in the map — never a wrong guess.
        assert "https://cinejoy.to/" not in results

    def test_maps_each_probed_url_to_its_availability(self, stub_render):
        stub_render({"https://flixer.gd/search?q=The+Matrix": _FLIXER_MISS})

        results = probe_availability([_link()])

        assert results["https://flixer.gd/search?q=The+Matrix"] == AvailabilityResult(
            status="unavailable", result_count=0
        )

    def test_a_render_failure_degrades_to_no_result_not_an_exception(
        self, stub_render
    ):
        stub_render(
            {"https://flixer.gd/search?q=The+Matrix": RuntimeError("browser died")}
        )

        # A blocked or crashed site is "we don't know", never a failed search
        # (SPEC.md boundaries: skip the site, don't fail the request).
        assert probe_availability([_link()]) == {}

    def test_never_probes_more_than_the_limit(self, stub_render):
        stub_render({}, default=_FLIXER_HIT)

        links = [
            _link(url=f"https://flixer.gd/search?q=t{n}", name=f"S{n}")
            for n in range(6)
        ]
        probe_availability(links, limit=2)

        assert len(stub_render.rendered) == 2

    def test_returns_empty_when_playwright_is_not_installed(self, monkeypatch):
        def raise_import(url, timeout_ms):
            raise ImportError("No module named 'playwright'")

        monkeypatch.setattr(availability, "_render_page_text", raise_import)

        # The whole feature is optional: without Playwright the search must
        # still work, just without availability information.
        assert probe_availability([_link()]) == {}

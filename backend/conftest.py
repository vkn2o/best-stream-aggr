"""Shared pytest configuration.

Ensures the backend package root is importable regardless of where pytest
is invoked from, and blocks live network calls: SPEC.md's testing strategy
requires deterministic, offline tests, and a route that quietly falls
through to the real FMHY endpoint would make CI depend on a third-party
site's uptime and markup.
"""
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scraper import availability, playback, tmdb_lookup  # noqa: E402


@pytest.fixture(autouse=True)
def block_live_network(monkeypatch, request):
    """Fail any test that reaches the network instead of stubbing it.

    Opt out with @pytest.mark.allow_network for a deliberate live check.
    """
    if request.node.get_closest_marker("allow_network"):
        return

    def blocked(*args, **kwargs):
        raise AssertionError(
            "live network call in a test — stub "
            "scraper.fmhy_source_list.fetch_video_markdown instead"
        )

    monkeypatch.setattr(requests, "get", blocked)

    # Same rule for the availability probe (task S3): a real Playwright run
    # would launch a browser and hit live sites, making the suite slow and
    # dependent on third-party uptime. Stub
    # scraper.availability._render_page_text in tests that need it.
    def blocked_render(*args, **kwargs):
        raise AssertionError(
            "live browser render in a test — stub "
            "scraper.availability._render_page_text instead"
        )

    monkeypatch.setattr(availability, "_render_page_text", blocked_render)

    # Same rule for the task-S4 playback probe, which is even more expensive
    # (it watches a video for ~10s). Stub scraper.playback._measure_playback
    # in tests that need it; the live checks live in tests/live/ behind the
    # live_browser marker.
    def blocked_playback(*args, **kwargs):
        raise AssertionError(
            "live browser playback in a test — stub "
            "scraper.playback._measure_playback instead"
        )

    monkeypatch.setattr(playback, "_measure_playback", blocked_playback)

    # Keep TMDB lookups deterministic and offline: whether a developer
    # happens to have a key exported must not change what the suite does.
    # Tests that want the lookup set the key themselves.
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    tmdb_lookup.clear_cache()

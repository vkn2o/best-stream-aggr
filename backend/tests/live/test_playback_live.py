"""Live browser checks for the task-S4 playback probe.

Excluded from the default run (see pytest.ini `addopts`). Run deliberately:

    python -m pytest -m live_browser

These launch real Chromium against live third-party sites, so they are slow
and can fail for reasons outside this codebase (a site is down, changed its
markup, or blocks headless browsers). That is exactly what they are for:
they answer "does our adapter still reach a real player?" rather than
"is our logic correct" — the offline tests in tests/test_playback.py cover
the logic.

A failure here is a signal to look at the adapter, not necessarily a bug in
this repo. Per docs/Constraints.md #5, the response to a site that blocks a
headless browser is to leave it alone and report "unknown", never to work
around the protection.
"""
import pytest

from scraper.playback import (
    _INSTRUMENT_JS,
    OBSERVATION_MS,
    _PLAYBACK_ADAPTERS,
    _measure_playback,
    parse_metrics,
)

pytestmark = [pytest.mark.live_browser, pytest.mark.allow_network]

_FLIXER_SEARCH = "https://flixer.gd/search?q=The+Matrix"


def test_flixer_adapter_reports_honestly_whether_it_reaches_a_player():
    """Documents the current, verified state of the Flixer adapter.

    As of the S4 build the answer is "it can't": Flixer's search results are
    click-driven cards with no title links, clicking one never navigates, and
    no <video> or iframe ever appears. The adapter therefore returns None and
    playback stays "unknown" for Flixer.

    When someone finds a real route to Flixer's player, this test flips to
    the `is not None` branch and should be rewritten to assert real metrics.
    """
    adapter = _PLAYBACK_ADAPTERS["flixer.gd"]

    raw = _measure_playback(
        _FLIXER_SEARCH, "The Matrix", adapter, observation_ms=OBSERVATION_MS
    )

    if raw is None:
        pytest.skip(
            "Flixer adapter still cannot reach a player — playback stays "
            "'unknown' for this site, which is the documented state"
        )

    # If a player *was* reached, the payload must be well-formed enough to
    # score, otherwise the adapter is reporting something we can't trust.
    metrics = parse_metrics(raw, observed_ms=OBSERVATION_MS)
    assert metrics.status == "measured"
    assert metrics.observed_ms == OBSERVATION_MS


def test_a_site_with_no_adapter_is_never_measured():
    """The registry is the only thing that authorises opening a site."""
    assert "cinejoy.to" not in _PLAYBACK_ADAPTERS


def test_the_instrumentation_measures_real_media_events_in_a_real_browser():
    """Proves the measuring machinery itself works, independent of any site.

    No streaming-site adapter can currently reach a player, so without this
    the injected script would be entirely unverified. It attaches the real
    instrumentation to a real <video> in real Chromium and dispatches genuine
    DOM media events, then checks the numbers that come back.

    Needs no network: the page is set inline.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content("<body><video id='v'></video></body>")
            video = page.wait_for_selector("video", state="attached")
            video.evaluate(_INSTRUMENT_JS)

            video.evaluate(
                """(video) => new Promise((done) => {
                    const fire = (name) => video.dispatchEvent(new Event(name));
                    setTimeout(() => fire('playing'), 300);
                    setTimeout(() => fire('waiting'), 900);
                    setTimeout(() => fire('playing'), 1500);
                    setTimeout(done, 1800);
                })"""
            )

            raw = video.evaluate(
                "() => { const s = window.__streamFinderPlayback; return s && "
                "{started: s.started, startupMs: s.startupMs, "
                "rebufferCount: s.rebufferCount, rebufferMs: s.rebufferMs}; }"
            )
        finally:
            browser.close()

    metrics = parse_metrics(raw, observed_ms=OBSERVATION_MS)

    assert metrics.status == "measured"
    assert metrics.started is True
    # The 'playing' event was fired ~300ms after instrumentation.
    assert 150 <= metrics.startup_ms <= 900
    assert metrics.rebuffer_count >= 1
    assert metrics.rebuffer_ms > 0

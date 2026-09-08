"""Tests for scraper/playback.py — task S4, measured playback quality.

The browser boundary (`_measure_playback`) is always stubbed; the metric
parsing, target selection and degradation logic on top of it run for real.
No test in this file may launch a browser.

The governing rule under test throughout: the app must never report a
playback quality it did not actually measure. Every failure path — no
adapter, no player, a timeout, a crash, a malformed payload, missing
Playwright — has to come out as "unknown", never as a number.
"""
import pytest

from scraper import Candidate, playback
from scraper.playback import (
    OBSERVATION_MS,
    PlaybackMetrics,
    parse_metrics,
    probe_playback,
)


class _WorkingAdapter:
    """A stand-in for a site whose player we can actually reach.

    Tests inject this rather than relying on whichever real adapters happen
    to be registered and enabled, so the suite tests the *logic* and not the
    current state of third-party sites.
    """

    domain = "flixer.gd"
    enabled = True

    def open_player(self, page, title):
        return True


@pytest.fixture(autouse=True)
def working_adapter(monkeypatch):
    monkeypatch.setattr(
        playback, "_PLAYBACK_ADAPTERS", {"flixer.gd": _WorkingAdapter()}
    )


def _candidate(site="flixer.gd", availability="available", deep=True, **kw):
    defaults = dict(
        title="The Matrix",
        url=f"https://{site}/search?q=The+Matrix",
        site_name=site,
        is_deep_link=deep,
        availability=availability,
    )
    defaults.update(kw)
    return Candidate(**defaults)


def _raw(**kw):
    """A well-formed payload as the injected JS returns it."""
    payload = {
        "started": True,
        "startupMs": 1200,
        "rebufferCount": 2,
        "rebufferMs": 900,
    }
    payload.update(kw)
    return payload


class TestParseMetrics:
    def test_reads_a_well_formed_payload(self):
        metrics = parse_metrics(_raw(), observed_ms=10_000)

        assert metrics == PlaybackMetrics(
            status="measured",
            started=True,
            startup_ms=1200,
            rebuffer_count=2,
            rebuffer_ms=900,
            observed_ms=10_000,
            failure=None,
        )

    def test_a_stream_that_never_started_is_a_measurement_not_an_unknown(self):
        # "We watched and it never played" is real evidence and must be kept
        # distinct from "we couldn't watch it".
        metrics = parse_metrics(
            _raw(started=False, startupMs=None), observed_ms=10_000
        )

        assert metrics.status == "measured"
        assert metrics.started is False

    @pytest.mark.parametrize(
        "bad",
        [
            None,
            "not-a-dict",
            ["list"],
            {},
            {"started": True},  # missing counters
            {"started": "yes", "startupMs": 1, "rebufferCount": 0, "rebufferMs": 0},
            {"started": True, "startupMs": "fast", "rebufferCount": 0, "rebufferMs": 0},
            {"started": True, "startupMs": 1, "rebufferCount": None, "rebufferMs": 0},
        ],
    )
    def test_a_malformed_payload_is_unknown_never_a_guess(self, bad):
        metrics = parse_metrics(bad, observed_ms=10_000)

        assert metrics.status == "unknown"
        assert metrics.failure == "bad_payload"
        assert metrics.startup_ms is None

    def test_negative_counters_are_rejected_rather_than_scored(self):
        assert parse_metrics(_raw(rebufferCount=-1), observed_ms=10_000).status == (
            "unknown"
        )


class TestProbePlayback:
    @pytest.fixture
    def stub_measure(self, monkeypatch):
        def install(result, record=None):
            def fake(url, title, adapter, observation_ms):
                if record is not None:
                    record.append(url)
                if isinstance(result, Exception):
                    raise result
                return result(url) if callable(result) else result

            monkeypatch.setattr(playback, "_measure_playback", fake)

        return install

    def test_measures_an_available_deep_linked_site_that_has_an_adapter(
        self, stub_measure
    ):
        stub_measure(_raw())

        results = probe_playback([_candidate()])

        assert results[_candidate().url].status == "measured"
        assert results[_candidate().url].rebuffer_count == 2

    def test_skips_a_site_the_title_is_not_available_on(self, stub_measure):
        probed = []
        stub_measure(_raw(), record=probed)

        # No point measuring playback of a title the site doesn't even have —
        # this is the main guard against opening every streaming site.
        results = probe_playback([_candidate(availability="unavailable")])

        assert probed == []
        assert results == {}

    def test_skips_a_site_whose_availability_is_unknown(self, stub_measure):
        probed = []
        stub_measure(_raw(), record=probed)

        probe_playback([_candidate(availability="unknown")])

        assert probed == []

    def test_skips_a_home_page_link_because_there_is_no_title_to_play(
        self, stub_measure
    ):
        probed = []
        stub_measure(_raw(), record=probed)

        probe_playback([_candidate(deep=False)])

        assert probed == []

    def test_skips_a_domain_with_no_playback_adapter(self, stub_measure):
        probed = []
        stub_measure(_raw(), record=probed)

        probe_playback([_candidate(site="cinejoy.to")])

        assert probed == []

    def test_skips_an_adapter_that_is_known_not_to_reach_a_player(
        self, stub_measure, monkeypatch
    ):
        class _Unusable:
            domain = "flixer.gd"
            enabled = False

            def open_player(self, page, title):
                return False

        monkeypatch.setattr(
            playback, "_PLAYBACK_ADAPTERS", {"flixer.gd": _Unusable()}
        )
        probed = []
        stub_measure(_raw(), record=probed)

        # Launching a browser only to have the adapter give up is pure waste
        # on every single search — don't open the site at all.
        assert probe_playback([_candidate()]) == {}
        assert probed == []

    def test_never_measures_more_sites_than_the_limit(self, stub_measure):
        probed = []
        stub_measure(_raw(), record=probed)

        candidates = [
            _candidate(url=f"https://flixer.gd/search?q=t{n}") for n in range(5)
        ]
        probe_playback(candidates, limit=2)

        assert len(probed) == 2

    def test_a_site_that_cannot_be_measured_is_absent_rather_than_guessed(
        self, stub_measure
    ):
        # None = the adapter never reached a player.
        stub_measure(None)

        assert probe_playback([_candidate()]) == {}

    def test_a_crash_on_one_site_does_not_stop_the_others(self, monkeypatch):
        def fake(url, title, adapter, observation_ms):
            if "first" in url:
                raise RuntimeError("player exploded")
            return _raw()

        monkeypatch.setattr(playback, "_measure_playback", fake)

        results = probe_playback(
            [
                _candidate(url="https://flixer.gd/search?q=first"),
                _candidate(url="https://flixer.gd/search?q=second"),
            ]
        )

        assert "https://flixer.gd/search?q=first" not in results
        assert results["https://flixer.gd/search?q=second"].status == "measured"

    def test_a_timeout_degrades_to_unknown_without_raising(self, stub_measure):
        stub_measure(TimeoutError("navigation timed out"))

        assert probe_playback([_candidate()]) == {}

    def test_returns_nothing_when_playwright_is_not_installed(self, stub_measure):
        stub_measure(ImportError("No module named 'playwright'"))

        # The whole feature is optional — search must still work.
        assert probe_playback([_candidate()]) == {}

    def test_uses_the_shared_observation_window_for_every_site(self, monkeypatch):
        windows = []

        def fake(url, title, adapter, observation_ms):
            windows.append(observation_ms)
            return _raw()

        monkeypatch.setattr(playback, "_measure_playback", fake)
        probe_playback(
            [
                _candidate(url="https://flixer.gd/search?q=a"),
                _candidate(url="https://flixer.gd/search?q=b"),
            ]
        )

        # Comparing sites is only fair if each was watched for equally long.
        assert windows == [OBSERVATION_MS, OBSERVATION_MS]

"""Task S4: how well does this source actually *play* the title?

Task S3 (availability.py) answers "does this site have the title". That is
not the same as "is this title watchable here" — a site can list a title and
then stall every few seconds. This module opens the playback page and
measures what the video actually does.

## The rule that shapes everything here

**Never report a playback quality that wasn't measured.** Every failure —
no adapter for the domain, no reachable player, a timeout, a crash, a
malformed payload, Playwright not installed — comes out as "unknown" and is
scored neutrally (see scoring/__init__.py). A confident wrong number is far
worse than no number: it would send someone to a source we never tested.

## Consistent methodology

Sites are only comparable if they were measured the same way, so every site
gets the identical treatment: the same fixed OBSERVATION_MS watch window,
the same event instrumentation, the same derived metrics. Nothing is
site-specific except *how to reach the player*, which is what an adapter is.

## Boundaries

Audio is muted before playing, which is what browser autoplay policy
requires of any page — it is not an attempt to look like something we're
not. We do not spoof fingerprints, solve challenges, or work around
anti-bot, login walls or DRM (docs/Constraints.md #5): a site that blocks a
headless browser is "unknown", and we leave it alone.

## Current adapter coverage — measured, not assumed

`flixer.gd` is the only site with a verified *availability* detector, so it
is the only playback candidate. Its search results are click-driven cards
with no title links (no `/movie/`, `/watch` or `/title/` hrefs anywhere in
the DOM). Clicking a card reveals inline detail but never navigates: across
repeated attempts the URL stayed on the search page, no `<video>` element
and no iframe ever appeared, and the only controls are site navigation.
So `FlixerPlaybackAdapter.open_player` honestly reports that it could not
reach a player, and Flixer's playback stays "unknown" until someone finds
(and verifies) a real route to its player. See docs/Decisions.md.
"""
import logging
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

_logger = logging.getLogger(__name__)

# Every site is watched for exactly this long, so rebuffer counts and
# buffering totals mean the same thing across sites.
OBSERVATION_MS = 10_000
# Playback measurement is the most expensive thing this app does, so only a
# couple of already-confirmed-available sources are ever opened.
DEFAULT_PLAYBACK_LIMIT = 2
NAVIGATION_TIMEOUT_MS = 25_000
PLAYER_READY_TIMEOUT_MS = 15_000


@dataclass
class PlaybackMetrics:
    """What a source's playback actually did during the observation window.

    `status` is "measured" only when the numbers below came from a real
    observation. "unknown" means we could not measure and are not guessing;
    `failure` says why.
    """

    status: str  # "measured" | "unknown"
    started: bool = False
    startup_ms: int | None = None
    rebuffer_count: float = 0  # fractional when averaged over sessions
    rebuffer_ms: int = 0
    observed_ms: int = 0
    failure: str | None = None
    # Where these numbers came from, and what they describe. "probed" is a
    # synthetic session this app ran; "reported" is a real viewer session
    # (see telemetry.py). `scope` distinguishes evidence about *this title*
    # from site-wide evidence — the UI must never present the second as the
    # first.
    provenance: str = "probed"
    sample_size: int | None = None
    scope: str | None = None


def unknown_playback(reason: str) -> PlaybackMetrics:
    """The only way this module ever reports "we don't know"."""
    return PlaybackMetrics(status="unknown", failure=reason)


class PlaybackAdapter(Protocol):
    """How to get from a site's search URL to a playing video on that site.

    Adapters hold *only* the site-specific navigation. Measurement is shared,
    so adding a site means implementing this one method — nothing else in
    this module or in scoring changes.
    """

    domain: str
    # False for an adapter that is registered but known not to reach a
    # player. probe_playback skips it entirely rather than launching a
    # browser, navigating, and then giving up on every single search.
    enabled: bool

    def open_player(self, page, title: str) -> bool:
        """Reach the playback page for `title`. False if it can't be done."""


class FlixerPlaybackAdapter:
    """flixer.gd — no reachable player found; reports failure honestly.

    Kept as a real registered adapter (rather than an empty registry) so the
    selection path is exercised and so there is an obvious place to put a
    working route once one is verified against the live site. See this
    module's docstring for what was tried.
    """

    domain = "flixer.gd"
    # Verified against the live site: no route to a player was found, so
    # there is nothing to gain by opening it. Flip this to True together
    # with a real open_player once one is found.
    enabled = False

    def open_player(self, page, title: str) -> bool:
        return False


_PLAYBACK_ADAPTERS: dict[str, PlaybackAdapter] = {
    "flixer.gd": FlixerPlaybackAdapter(),
}

# Installed on the page to watch the video element. Accumulates into one
# object rather than streaming events out, so a single read at the end of
# the window gives the whole picture.
_INSTRUMENT_JS = """
(video) => {
  const state = {
    started: false, startupMs: null, rebufferCount: 0, rebufferMs: 0,
    // _t0 is the play request: this runs immediately before video.play()
    // below, matching how the userscript measures start-up from the
    // viewer pressing play rather than from page load.
    _t0: performance.now(), _waitingSince: null, _lastTime: -1,
  };
  window.__streamFinderPlayback = state;

  video.addEventListener('playing', () => {
    if (!state.started) {
      state.started = true;
      state.startupMs = Math.round(performance.now() - state._t0);
    } else if (state._waitingSince !== null) {
      state.rebufferMs += Math.round(performance.now() - state._waitingSince);
      state._waitingSince = null;
    }
  });
  const stall = () => {
    if (state.started && state._waitingSince === null) {
      state.rebufferCount += 1;
      state._waitingSince = performance.now();
    }
  };
  video.addEventListener('waiting', stall);
  video.addEventListener('stalled', stall);

  // A video can sit in a "playing" state while currentTime never advances;
  // the events alone would call that flawless playback.
  setInterval(() => {
    if (!state.started) return;
    if (video.currentTime === state._lastTime && !video.paused) stall();
    else if (video.currentTime !== state._lastTime && state._waitingSince !== null) {
      state.rebufferMs += Math.round(performance.now() - state._waitingSince);
      state._waitingSince = null;
    }
    state._lastTime = video.currentTime;
  }, 500);

  video.muted = true;
  const play = video.play();
  if (play && play.catch) play.catch(() => {});
}
"""


def parse_metrics(raw, observed_ms: int) -> PlaybackMetrics:
    """Turn the injected script's payload into metrics, or "unknown".

    The payload crosses a browser boundary and is therefore untrusted in
    shape, like every other external response in this codebase
    (docs/Constraints.md #2). Anything missing, mistyped or nonsensical is
    "unknown" rather than a number we half-invented.
    """
    if not isinstance(raw, dict):
        return unknown_playback("bad_payload")

    started = raw.get("started")
    startup_ms = raw.get("startupMs")
    rebuffer_count = raw.get("rebufferCount")
    rebuffer_ms = raw.get("rebufferMs")

    if not isinstance(started, bool):
        return unknown_playback("bad_payload")
    # bool is a subclass of int, so it has to be excluded explicitly.
    if not isinstance(rebuffer_count, int) or isinstance(rebuffer_count, bool):
        return unknown_playback("bad_payload")
    if not isinstance(rebuffer_ms, int) or isinstance(rebuffer_ms, bool):
        return unknown_playback("bad_payload")
    if startup_ms is not None and (
        not isinstance(startup_ms, int) or isinstance(startup_ms, bool)
    ):
        return unknown_playback("bad_payload")
    if rebuffer_count < 0 or rebuffer_ms < 0 or (startup_ms or 0) < 0:
        return unknown_playback("bad_payload")

    return PlaybackMetrics(
        status="measured",
        started=started,
        startup_ms=startup_ms,
        rebuffer_count=rebuffer_count,
        rebuffer_ms=rebuffer_ms,
        observed_ms=observed_ms,
        failure=None,
    )


def probe_playback(
    candidates,
    limit: int = DEFAULT_PLAYBACK_LIMIT,
    observation_ms: int = OBSERVATION_MS,
) -> dict[str, PlaybackMetrics]:
    """Measure playback for the best few candidates; url -> metrics.

    Only sources worth the cost are opened: the title must be *confirmed
    available* there (task S3), the link must be a deep link into the site
    for this title, and the domain must have a playback adapter. With
    today's coverage that is at most one site per search, and never a site
    already known not to have the title.

    Only definite measurements are returned. A source missing from the map
    simply wasn't measured, and callers must treat it as unknown.
    """
    targets = [
        candidate
        for candidate in candidates
        if candidate.availability == "available"
        and candidate.is_deep_link
        and _usable_adapter(candidate.url) is not None
    ][:limit]

    results: dict[str, PlaybackMetrics] = {}
    for candidate in targets:
        adapter = _usable_adapter(candidate.url)
        try:
            raw = _measure_playback(
                candidate.url, candidate.title, adapter, observation_ms
            )
        except ImportError:
            _logger.warning(
                "playback probe skipped: Playwright is not installed"
            )
            return results
        except Exception:
            # A blocked site, a dead player, a timeout or a crashed browser
            # is "we don't know" — never a failed search.
            _logger.warning(
                "playback probe failed for %s", candidate.url, exc_info=True
            )
            continue

        if raw is None:
            # The adapter couldn't reach a player at all.
            _logger.info("no reachable player for %s", candidate.url)
            continue

        metrics = parse_metrics(raw, observed_ms=observation_ms)
        if metrics.status == "measured":
            results[candidate.url] = metrics

    return results


def _usable_adapter(url: str):
    """The adapter that can actually measure `url`, or None."""
    adapter = _PLAYBACK_ADAPTERS.get(_domain(url))
    if adapter is None or not getattr(adapter, "enabled", True):
        return None
    return adapter


def _measure_playback(url: str, title: str, adapter, observation_ms: int):
    """Open `url`, reach the player, watch it, and return the raw payload.

    The single Playwright boundary — stubbed in every unit test and blocked
    in conftest.py, so the suite never launches a browser. Returns None when
    no player could be reached. Imported lazily so neither importing this
    module nor running a search requires Playwright.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(
                url, timeout=NAVIGATION_TIMEOUT_MS, wait_until="domcontentloaded"
            )

            if not adapter.open_player(page, title):
                return None

            video = _find_video(page)
            if video is None:
                return None

            video.evaluate(_INSTRUMENT_JS)
            page.wait_for_timeout(observation_ms)
            return video.evaluate(
                "() => { const s = window.__streamFinderPlayback; return s && "
                "{started: s.started, startupMs: s.startupMs, "
                "rebufferCount: s.rebufferCount, rebufferMs: s.rebufferMs}; }"
            )
        finally:
            browser.close()


def _find_video(page):
    """Find a <video> on the page or in any frame (players are often iframed)."""
    for frame in [page, *page.frames]:
        try:
            handle = frame.wait_for_selector(
                "video", timeout=PLAYER_READY_TIMEOUT_MS, state="attached"
            )
        except Exception:
            continue
        if handle is not None:
            return handle
    return None


def _domain(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host

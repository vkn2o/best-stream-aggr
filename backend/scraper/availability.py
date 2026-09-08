"""Task S3: does this site actually have the searched title?

This is the app's only genuinely *title-dependent* ranking signal. Stage A
(FMHY's list) and Stage B (link building) both describe sites, not titles —
so without this, every search scores the same sites identically and returns
the same winner regardless of what was searched (see docs/Decisions.md).

Why a rendering browser: every candidate site renders its search results
client-side, so the HTML a plain request returns contains no results at all.
The only way to see whether a site has a title is to render its search page.

Why the result *count* and not the title text: these sites echo the search
term back into the page ("Results for: <query>") even when they have zero
matches, so a substring check reports every title as available on every
site. Verified against live pages — a nonsense query renders
`0 results found` while a real one renders `59 results found`, and only the
count distinguishes them.

Only domains with a detector verified against the live site appear in
`_AVAILABILITY_DETECTORS`. Anything else stays "unknown" rather than
guessing: a wrong confident answer is worse than no answer. A site that
blocks headless browsers, renders an empty body, or changes its layout also
degrades to "unknown" — never to a failed search (SPEC.md boundaries: skip
the site, don't defeat the protection and don't fail the request).
"""
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from scraper.site_search import SiteLink

_logger = logging.getLogger(__name__)

# Rendering is slow (seconds per site), so only the strongest few candidates
# are ever probed.
DEFAULT_PROBE_LIMIT = 3
DEFAULT_TIMEOUT_MS = 20_000

_FLIXER_RESULT_COUNT = re.compile(r"(\d+)\s+results?\s+found", re.IGNORECASE)


@dataclass
class AvailabilityResult:
    """Whether a site has the searched title, and how many matches it showed."""

    status: str  # "available" | "unavailable" | "unknown"
    result_count: int | None


def _flixer_detector(page_text: str) -> AvailabilityResult:
    match = _FLIXER_RESULT_COUNT.search(page_text)
    if match is None:
        return _UNKNOWN
    count = int(match.group(1))
    return AvailabilityResult(
        status="available" if count > 0 else "unavailable", result_count=count
    )


# domain -> detector. Each one is verified against the live rendered page;
# see the S3 spike notes in docs/Decisions.md for what each site renders.
_AVAILABILITY_DETECTORS = {
    "flixer.gd": _flixer_detector,
}

_UNKNOWN = AvailabilityResult(status="unknown", result_count=None)


def detect_availability(domain: str, page_text: str) -> AvailabilityResult:
    """Read a rendered page's text as an availability answer for `domain`."""
    detector = _AVAILABILITY_DETECTORS.get(domain)
    if detector is None or not page_text.strip():
        return _UNKNOWN
    return detector(page_text)


def probe_availability(
    links: list[SiteLink],
    limit: int = DEFAULT_PROBE_LIMIT,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> dict[str, AvailabilityResult]:
    """Render up to `limit` probeable links and report what each site has.

    Returns a url -> AvailabilityResult map containing only the links that
    produced a definite answer. A link is probeable only if it's a deep link
    into a site's search (a home-page link has no title to check) whose
    domain has a verified detector.
    """
    probeable = [
        link
        for link in links
        if link.is_deep_link and _domain(link.url) in _AVAILABILITY_DETECTORS
    ][:limit]

    results: dict[str, AvailabilityResult] = {}
    for link in probeable:
        try:
            page_text = _render_page_text(link.url, timeout_ms)
        except ImportError:
            # Playwright not installed — the whole feature is optional.
            _logger.warning(
                "availability probe skipped: Playwright is not installed"
            )
            return results
        except Exception:
            # A blocked, crashed or timed-out site is "unknown", not a
            # failure of the search it belongs to.
            _logger.warning(
                "availability probe failed for %s", link.url, exc_info=True
            )
            continue

        result = detect_availability(_domain(link.url), page_text)
        if result.status != "unknown":
            results[link.url] = result

    return results


def _render_page_text(url: str, timeout_ms: int) -> str:
    """Render `url` in a headless browser and return its visible body text.

    The single Playwright boundary — stubbed in every test, so the suite
    never launches a browser. Imported lazily so that neither importing this
    module nor running a search requires Playwright to be installed.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            # These are client-rendered apps: the results appear after the
            # initial HTML, so the page needs a moment past DOM-ready.
            page.wait_for_timeout(6_000)
            return page.inner_text("body")
        finally:
            browser.close()


def _domain(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host

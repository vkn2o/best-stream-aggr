"""Tests for fetching + caching FMHY's video markdown.

The network call itself is stubbed — it's the one boundary that's slow and
non-deterministic, which is exactly where test-driven-development says a
test double is warranted. Everything below the stub is real code.
"""
import requests
import pytest

from scraper import fmhy_source_list
from scraper.fmhy_source_list import get_streaming_sites

_MARKDOWN = """# ► Streaming Sites

## ▷ Stream Aggregators

* ⭐ **[Alpha](https://alpha.test/)** - Movies / TV
* [Beta](https://beta.test/) - Movies / TV
"""


@pytest.fixture(autouse=True)
def clear_cache():
    fmhy_source_list.clear_cache()
    yield
    fmhy_source_list.clear_cache()


@pytest.fixture
def stub_fetch(monkeypatch):
    calls = []

    def fake_fetch():
        calls.append(1)
        return _MARKDOWN

    monkeypatch.setattr(fmhy_source_list, "fetch_video_markdown", fake_fetch)
    return calls


def test_get_streaming_sites_returns_parsed_sites_best_first(stub_fetch):
    sites = get_streaming_sites()

    assert [site.name for site in sites] == ["Alpha", "Beta"]


def test_get_streaming_sites_caches_between_calls(stub_fetch):
    get_streaming_sites()
    get_streaming_sites()

    assert len(stub_fetch) == 1


def test_get_streaming_sites_refetches_when_forced(stub_fetch):
    get_streaming_sites()
    get_streaming_sites(force_refresh=True)

    assert len(stub_fetch) == 2


def test_get_streaming_sites_refetches_after_the_cache_expires(
    stub_fetch, monkeypatch
):
    clock = [1000.0]
    monkeypatch.setattr(fmhy_source_list, "_now", lambda: clock[0])

    get_streaming_sites()
    clock[0] += fmhy_source_list.CACHE_TTL_SECONDS + 1
    get_streaming_sites()

    assert len(stub_fetch) == 2


def test_serves_stale_cache_when_a_refresh_fetch_fails(monkeypatch):
    # Regression test: FMHY being transiently unreachable must not take
    # down every search when a perfectly good (if expired) list is cached —
    # FMHY's own directory changes "on the order of days" (see module
    # docstring), so a stale-by-an-hour list is still almost certainly
    # correct, and is strictly better than a hard failure.
    monkeypatch.setattr(fmhy_source_list, "fetch_video_markdown", lambda: _MARKDOWN)
    first = fmhy_source_list.get_streaming_sites()

    def boom():
        raise requests.ConnectionError("FMHY unreachable")

    monkeypatch.setattr(fmhy_source_list, "fetch_video_markdown", boom)

    served = fmhy_source_list.get_streaming_sites(force_refresh=True)

    assert served == first


def test_raises_when_the_fetch_fails_and_there_is_no_cache_at_all(monkeypatch):
    def boom():
        raise requests.ConnectionError("FMHY unreachable")

    monkeypatch.setattr(fmhy_source_list, "fetch_video_markdown", boom)

    with pytest.raises(requests.ConnectionError):
        fmhy_source_list.get_streaming_sites()


def test_raises_when_the_fetch_fails_after_the_cache_expires(monkeypatch, caplog):
    clock = [1000.0]
    monkeypatch.setattr(fmhy_source_list, "_now", lambda: clock[0])
    monkeypatch.setattr(fmhy_source_list, "fetch_video_markdown", lambda: _MARKDOWN)
    fmhy_source_list.get_streaming_sites()

    clock[0] += fmhy_source_list.CACHE_TTL_SECONDS + 1

    def boom():
        raise requests.ConnectionError("FMHY unreachable")

    monkeypatch.setattr(fmhy_source_list, "fetch_video_markdown", boom)

    # An expired-but-present cache is still served on failure — better
    # stale than down (see the two tests above) — so this only documents
    # the one case where there's truly nothing to fall back on: no cache
    # was ever the state to begin with.
    fmhy_source_list.clear_cache()
    with pytest.raises(requests.ConnectionError):
        fmhy_source_list.get_streaming_sites()

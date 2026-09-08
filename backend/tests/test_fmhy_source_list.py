"""Tests for scraper/fmhy_source_list.py — parsing FMHY's video markdown.

Parses a saved excerpt of FMHY's real `docs/video.md` (see
tests/fixtures/fmhy_video_excerpt.md) rather than hitting the network, per
SPEC.md's testing strategy: FMHY's page changes without notice, so CI must
be deterministic.
"""
from pathlib import Path

from scraper.fmhy_source_list import parse_streaming_sites, rank_sites

FIXTURE = (
    Path(__file__).parent / "fixtures" / "fmhy_video_excerpt.md"
).read_text(encoding="utf-8")


def test_parses_sites_in_document_order_starting_at_rank_one():
    sites = parse_streaming_sites(FIXTURE)

    assert sites[0].name == "Cinejoy"
    assert sites[0].url == "https://cinejoy.to/"
    assert sites[0].rank == 1


def test_ranks_are_sequential():
    sites = parse_streaming_sites(FIXTURE)

    assert [site.rank for site in sites] == list(range(1, len(sites) + 1))


def test_marks_starred_sites_as_starred():
    sites = parse_streaming_sites(FIXTURE)
    by_name = {site.name: site for site in sites}

    assert by_name["Cinejoy"].starred is True
    assert by_name["Vivarium"].starred is False


def test_skips_note_bullets():
    sites = parse_streaming_sites(FIXTURE)

    assert not any(site.name == "Note" for site in sites)


def test_skips_cross_reference_links_to_reddit_and_github():
    sites = parse_streaming_sites(FIXTURE)

    assert not any("reddit.com" in site.url for site in sites)
    assert not any("github.com" in site.url for site in sites)


def test_ignores_sections_outside_the_streaming_sites_section():
    sites = parse_streaming_sites(FIXTURE)

    # PlayTorrio lives under "# ► Streaming Apps", not "# ► Streaming Sites"
    assert not any(site.name == "PlayTorrio" for site in sites)


def test_records_the_subsection_each_site_came_from():
    sites = parse_streaming_sites(FIXTURE)
    by_name = {site.name: site for site in sites}

    assert by_name["Cinejoy"].section == "Stream Aggregators"
    assert by_name["Boomflix"].section == "Dedicated-Server"


def test_returns_empty_list_when_there_is_no_streaming_sites_section():
    assert parse_streaming_sites("# ► Something Else\n\n* [A](https://a.test/)") == []


def test_rank_sites_puts_starred_sites_before_unstarred_ones():
    sites = parse_streaming_sites(FIXTURE)

    ranked = rank_sites(sites)

    starred_flags = [site.starred for site in ranked]
    assert starred_flags == sorted(starred_flags, reverse=True)


def test_rank_sites_preserves_fmhy_order_within_the_starred_group():
    sites = parse_streaming_sites(FIXTURE)

    ranked = rank_sites(sites)

    starred_ranks = [site.rank for site in ranked if site.starred]
    assert starred_ranks == sorted(starred_ranks)

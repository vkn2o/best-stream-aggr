"""Tests for the scoring package's public interface.

Ranking currently derives from FMHY's own ordering (star + list position);
the latency probe and reliability allowlist are still task S4, so
latency_score is a constant placeholder that can't affect ordering.
"""
import pytest

from scraper import Candidate
from scraper.playback import PlaybackMetrics
from scoring import ScoreResult, pick_best


def _candidate(site_name: str, rank: int, starred: bool = False, **kwargs):
    return Candidate(
        title="The Matrix",
        url=f"https://{site_name}/watch",
        site_name=site_name,
        rank=rank,
        starred=starred,
        **kwargs,
    )


def test_pick_best_returns_a_score_result_wrapping_the_winning_candidate():
    candidate = _candidate("a.test", rank=1)

    result = pick_best([candidate])

    assert isinstance(result, ScoreResult)
    assert result.candidate is candidate


def test_pick_best_prefers_a_starred_site_over_an_unstarred_one():
    unstarred = _candidate("a.test", rank=1, starred=False)
    starred = _candidate("b.test", rank=2, starred=True)

    result = pick_best([unstarred, starred])

    assert result.candidate is starred


def test_pick_best_prefers_the_higher_fmhy_position_among_equal_sites():
    lower = _candidate("b.test", rank=5, starred=True)
    higher = _candidate("a.test", rank=1, starred=True)

    result = pick_best([lower, higher])

    assert result.candidate is higher


def test_pick_best_prefers_a_candidate_with_known_subtitles_when_rank_is_equal():
    unknown_subs = _candidate("a.test", rank=1, subtitle_status="unknown")
    known_subs = _candidate("b.test", rank=1, subtitle_status="available")

    result = pick_best([unknown_subs, known_subs])

    assert result.candidate is known_subs


def test_pick_best_gives_no_subtitle_credit_for_unknown_status():
    result = pick_best([_candidate("a.test", rank=1, subtitle_status="unknown")])

    assert result.subtitle_score == 0.0


def test_pick_best_prefers_a_deep_link_over_a_home_page_link_when_tied():
    home_only = _candidate("a.test", rank=1, is_deep_link=False)
    deep = _candidate("b.test", rank=1, is_deep_link=True)

    result = pick_best([home_only, deep])

    assert result.candidate is deep


def test_a_starred_site_still_outranks_an_unstarred_deep_linked_one():
    starred_home_only = _candidate("a.test", rank=2, starred=True, is_deep_link=False)
    unstarred_deep = _candidate("b.test", rank=1, starred=False, is_deep_link=True)

    result = pick_best([starred_home_only, unstarred_deep])

    assert result.candidate is starred_home_only


class TestAvailabilityScoring:
    """Task S3: a confirmed per-title availability answer drives ranking.

    This is the only title-dependent signal in the whole scorer — without
    it every query scores identical sites identically and returns the same
    winner regardless of what was searched.
    """

    def test_a_site_confirmed_to_have_the_title_outranks_an_unprobed_one(self):
        # Confirmed evidence beats FMHY's general-purpose assumption, even
        # when the unprobed site is better placed in FMHY's list.
        unprobed_top = _candidate("a.test", rank=1, starred=True)
        confirmed = _candidate(
            "b.test", rank=7, starred=True, is_deep_link=True, availability="available"
        )

        assert pick_best([unprobed_top, confirmed]).candidate is confirmed

    def test_a_site_confirmed_not_to_have_the_title_is_demoted(self):
        missing = _candidate(
            "a.test",
            rank=1,
            starred=True,
            is_deep_link=True,
            availability="unavailable",
        )
        unprobed = _candidate("b.test", rank=9, starred=False)

        assert pick_best([missing, unprobed]).candidate is unprobed

    def test_unknown_availability_is_neutral(self):
        # An unprobeable site must not be punished for being unprobeable.
        unknown = _candidate("a.test", rank=1, starred=True, availability="unknown")
        default = _candidate("b.test", rank=1, starred=True)

        assert pick_best([unknown]).total_score == pick_best([default]).total_score

    def test_available_outranks_unavailable_all_else_equal(self):
        has_it = _candidate("a.test", rank=5, starred=True, availability="available")
        lacks_it = _candidate(
            "b.test", rank=5, starred=True, availability="unavailable"
        )

        assert pick_best([lacks_it, has_it]).candidate is has_it

    def test_the_same_sites_rank_differently_for_titles_with_different_availability(
        self,
    ):
        """The bug this whole feature exists to fix.

        Same two sites, same FMHY ranks — only the per-title availability
        differs, and that alone must change which site wins.
        """
        def candidates_for(flixer_has_it: bool):
            return [
                _candidate("cinejoy.to", rank=1, starred=True),
                _candidate(
                    "flixer.gd",
                    rank=7,
                    starred=True,
                    is_deep_link=True,
                    availability="available" if flixer_has_it else "unavailable",
                ),
            ]

        winner_when_present = pick_best(candidates_for(True)).candidate.site_name
        winner_when_absent = pick_best(candidates_for(False)).candidate.site_name

        assert winner_when_present == "flixer.gd"
        assert winner_when_absent == "cinejoy.to"
        assert winner_when_present != winner_when_absent


class TestPlaybackScoring:
    """Task S4: measured playback quality drives the recommendation.

    The point of these is that FMHY's ranking must stop being the last word
    once we have actually watched the stream.
    """

    @staticmethod
    def _measured(started=True, startup_ms=1000, rebuffer_count=0, rebuffer_ms=0):
        return PlaybackMetrics(
            status="measured",
            started=started,
            startup_ms=startup_ms,
            rebuffer_count=rebuffer_count,
            rebuffer_ms=rebuffer_ms,
            observed_ms=10_000,
        )

    def test_unmeasured_playback_scores_neutral(self):
        # A source we couldn't test must be neither rewarded nor punished.
        assert pick_best([_candidate("a.test", rank=1)]).latency_score == 0.0

    def test_unknown_status_is_also_neutral(self):
        candidate = _candidate(
            "a.test", rank=1, playback=PlaybackMetrics(status="unknown", failure="x")
        )

        assert pick_best([candidate]).latency_score == 0.0

    def test_smooth_playback_scores_positively(self):
        candidate = _candidate("a.test", rank=1, playback=self._measured())

        assert pick_best([candidate]).latency_score > 0

    def test_a_stream_that_never_started_is_scored_worst(self):
        candidate = _candidate(
            "a.test", rank=1, playback=self._measured(started=False, startup_ms=None)
        )

        assert pick_best([candidate]).latency_score < 0

    def test_fewer_rebuffer_events_beat_more(self):
        smooth = _candidate("a.test", rank=1, playback=self._measured())
        choppy = _candidate(
            "b.test",
            rank=1,
            playback=self._measured(rebuffer_count=4, rebuffer_ms=3000),
        )

        assert pick_best([choppy, smooth]).candidate is smooth

    def test_shorter_total_buffering_beats_longer_at_equal_event_counts(self):
        brief = _candidate(
            "a.test", rank=1, playback=self._measured(rebuffer_count=2, rebuffer_ms=400)
        )
        long = _candidate(
            "b.test", rank=1, playback=self._measured(rebuffer_count=2, rebuffer_ms=4000)
        )

        assert pick_best([long, brief]).candidate is brief

    def test_a_faster_start_beats_a_slower_one(self):
        quick = _candidate("a.test", rank=1, playback=self._measured(startup_ms=800))
        slow = _candidate("b.test", rank=1, playback=self._measured(startup_ms=7500))

        assert pick_best([slow, quick]).candidate is quick

    def test_a_lower_ranked_source_wins_on_substantially_better_playback(self):
        """The headline requirement: measured evidence beats FMHY position."""
        fmhy_favourite = _candidate(
            "cinejoy.to",
            rank=1,
            starred=True,
            playback=self._measured(
                started=True, startup_ms=7000, rebuffer_count=5, rebuffer_ms=5000
            ),
        )
        lower_but_smooth = _candidate(
            "flixer.gd",
            rank=7,
            starred=True,
            is_deep_link=True,
            availability="available",
            playback=self._measured(startup_ms=900),
        )

        assert pick_best([fmhy_favourite, lower_but_smooth]).candidate is (
            lower_but_smooth
        )

    def test_a_top_ranked_source_does_not_win_when_its_playback_is_poor(self):
        top_but_broken = _candidate(
            "cinejoy.to",
            rank=1,
            starred=True,
            playback=self._measured(started=False, startup_ms=None),
        )
        untested = _candidate("other.test", rank=9, starred=False)

        assert pick_best([top_but_broken, untested]).candidate is untested

    def test_measured_failure_ranks_below_an_untested_source(self):
        # "We watched it and it never played" is worse than "we don't know".
        failed = _candidate(
            "a.test",
            rank=1,
            starred=True,
            playback=self._measured(started=False, startup_ms=None),
        )
        untested = _candidate("b.test", rank=1, starred=True)

        assert pick_best([failed, untested]).candidate is untested

    def test_total_score_still_sums_its_components(self):
        result = pick_best(
            [_candidate("a.test", rank=1, starred=True, playback=self._measured())]
        )

        assert result.total_score == pytest.approx(
            result.reliability_score + result.subtitle_score + result.latency_score
        )


def test_a_player_link_beats_a_search_link_on_the_same_site_footing():
    # Landing on the title itself is strictly better than landing on a
    # search page the user still has to click through.
    search = _candidate("a.test", rank=1, is_deep_link=True, link_kind="search")
    player = _candidate("b.test", rank=1, is_deep_link=True, link_kind="title")

    assert pick_best([search, player]).candidate is player


def test_the_player_link_bonus_does_not_outweigh_availability():
    # A player link to a site that doesn't have the title is still useless.
    player_but_missing = _candidate(
        "a.test", rank=1, is_deep_link=True, link_kind="title",
        availability="unavailable",
    )
    plain_home_link = _candidate("b.test", rank=2, starred=True)

    assert pick_best([player_but_missing, plain_home_link]).candidate is (
        plain_home_link
    )


def test_pick_best_raises_value_error_on_empty_candidate_list():
    with pytest.raises(ValueError):
        pick_best([])


def test_pick_best_result_total_score_is_the_sum_of_its_components():
    result = pick_best([_candidate("a.test", rank=1, starred=True)])

    assert result.total_score == pytest.approx(
        result.reliability_score + result.subtitle_score + result.latency_score
    )

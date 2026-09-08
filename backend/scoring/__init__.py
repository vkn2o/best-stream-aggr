"""Scoring interface.

Ranking currently rests on FMHY's own curation — its editors have already
done the "which of these actually works well" evaluation that this app would
otherwise have to guess at. A starred entry outranks an unstarred one, and
among equals the higher position in FMHY's list wins.

Task S4 replaces the constant `latency_score` with a real probe and the
star/position reliability with a maintained allowlist. ScoreResult's shape
stays the same, so routes built on it don't change.
"""
from dataclasses import dataclass

from scraper import Candidate

_STARRED_RELIABILITY = 1.0
_UNSTARRED_RELIABILITY = 0.5
_SUBTITLE_BONUS = 0.2
# A verified deep link into the site's search beats landing on its home
# page. Folded into reliability (rather than added as a fourth component)
# to keep the ScoreResult contract stable, and kept small enough that
# position + deep-link together stay under the 0.5 starred/unstarred gap —
# so star tier still dominates.
_DEEP_LINK_BONUS = 0.1
# A link straight to the title's player beats one to a page of search
# results the user still has to click through. Deliberately small: it breaks
# ties between comparable sites without letting link precision outweigh
# whether the site actually has the title at all.
_TITLE_LINK_BONUS = 0.05
# Task S4. `latency_score` was reserved for exactly this: a real measurement
# of how a source behaves for the searched title. It stays 0.0 whenever
# playback wasn't measured, so an untested source is never rewarded or
# punished for being untestable.
_UNMEASURED_LATENCY_SCORE = 0.0

# A stream we watched and which never played is the worst possible outcome —
# worse than an untested source (0.0), because we have positive evidence it
# doesn't work rather than an open question.
_PLAYBACK_FAILED = -1.5
# Credit for playing at all, before start-up speed and buffering adjust it.
_PLAYBACK_BASE = 0.4
# Start-up: full credit under _PLAYBACK_FAST_START_MS, tapering to none by
# _PLAYBACK_SLOW_START_MS.
_PLAYBACK_STARTUP_WEIGHT = 0.3
_PLAYBACK_FAST_START_MS = 2_000
_PLAYBACK_SLOW_START_MS = 8_000
# Buffering is penalised twice on purpose: once per interruption (a stutter
# every few seconds ruins a viewing even if each one is short) and once for
# the share of the window actually spent waiting.
_PLAYBACK_EVENT_PENALTY = 0.2
_PLAYBACK_TIME_PENALTY = 0.6
# Clamped so measured playback can outweigh FMHY's star/position spread
# (max 1.5) without any single term running away with the ranking.
_PLAYBACK_SCORE_FLOOR = -1.5
_PLAYBACK_SCORE_CEILING = 1.0

# Task S3. Confirmed per-title availability is the only signal here that
# depends on *what was searched* rather than on the site alone — without it
# FMHY's rank-1 site wins every search regardless of whether it actually has
# the title, which is exactly the bug this exists to fix.
#
# Deliberately asymmetric, and the two magnitudes mean different things:
#
# "available" (+0.5) *outweighs* the star/position gap without erasing it —
# a confirmed hit lifts a well-placed site above FMHY's top general-purpose
# pick (1.4), while a deeply-buried unstarred site with the title still
# loses to a starred rank-1 aggregator. Curation still counts for something.
#
# "unavailable" (-2.0) is a *categorical* demotion, not a penalty to be
# weighed. A site we've confirmed doesn't have this title is a guaranteed
# wasted click, so it must rank below every merely-unprobed site. That means
# exceeding the entire reliability spread (max 1.5 = starred + rank 1 + deep
# link), so the demotion is guaranteed rather than incidentally true for the
# rank values we happen to see today.
#
# "unknown" is neutral: a site we couldn't probe must never be punished for
# being unprobeable — most sites can't be probed at all (see availability.py).
_AVAILABILITY_SCORES = {
    "available": 0.5,
    "unavailable": -2.0,
    "unknown": 0.0,
}


@dataclass
class ScoreResult:
    """The winning candidate plus its component and total scores."""

    candidate: Candidate
    reliability_score: float
    subtitle_score: float
    latency_score: float
    total_score: float


def pick_best(candidates: list[Candidate]) -> ScoreResult:
    """Score every candidate and return the highest-scoring one.

    Raises ValueError if `candidates` is empty — there's nothing to pick.
    """
    if not candidates:
        raise ValueError("pick_best requires at least one candidate")

    scored = [_score(candidate) for candidate in candidates]
    return max(scored, key=lambda result: result.total_score)


def _score(candidate: Candidate) -> ScoreResult:
    # Availability is folded into reliability rather than added as a fourth
    # component, so the ScoreResult contract the frontend renders stays as
    # it is — the candidate still carries the raw status for display.
    reliability_score = (
        (_STARRED_RELIABILITY if candidate.starred else _UNSTARRED_RELIABILITY)
        + _position_score(candidate.rank)
        + (_DEEP_LINK_BONUS if candidate.is_deep_link else 0.0)
        + _AVAILABILITY_SCORES.get(candidate.availability, 0.0)
        + (_TITLE_LINK_BONUS if candidate.link_kind == "title" else 0.0)
    )
    # Only a positively-known subtitle track earns credit; "unknown" (the
    # current default for every candidate) earns nothing rather than a guess.
    subtitle_score = (
        _SUBTITLE_BONUS if candidate.subtitle_status == "available" else 0.0
    )
    latency_score = _playback_score(candidate.playback)
    return ScoreResult(
        candidate=candidate,
        reliability_score=reliability_score,
        subtitle_score=subtitle_score,
        latency_score=latency_score,
        total_score=reliability_score + subtitle_score + latency_score,
    )


def _playback_score(playback) -> float:
    """Turn measured playback behaviour into a ranking contribution.

    Returns 0.0 for anything unmeasured. This function is the only place
    that decides what "good playback" means, and it only ever sees numbers
    that came from a real observation (see scraper/playback.py).
    """
    if playback is None or playback.status != "measured":
        return _UNMEASURED_LATENCY_SCORE

    if not playback.started:
        return _PLAYBACK_FAILED

    score = _PLAYBACK_BASE + _PLAYBACK_STARTUP_WEIGHT * _startup_quality(
        playback.startup_ms
    )
    score -= _PLAYBACK_EVENT_PENALTY * playback.rebuffer_count
    if playback.observed_ms > 0:
        score -= _PLAYBACK_TIME_PENALTY * (
            playback.rebuffer_ms / playback.observed_ms
        )

    return max(_PLAYBACK_SCORE_FLOOR, min(_PLAYBACK_SCORE_CEILING, score))


def _startup_quality(startup_ms: int | None) -> float:
    """1.0 for a near-instant start, decaying to 0.0 for a very slow one."""
    if startup_ms is None:
        return 0.0
    if startup_ms <= _PLAYBACK_FAST_START_MS:
        return 1.0
    if startup_ms >= _PLAYBACK_SLOW_START_MS:
        return 0.0
    span = _PLAYBACK_SLOW_START_MS - _PLAYBACK_FAST_START_MS
    return (_PLAYBACK_SLOW_START_MS - startup_ms) / span


def _position_score(rank: int) -> float:
    """Decay by FMHY list position: rank 1 scores highest, later ranks less.

    Kept below the star/unstarred gap (0.5) so position breaks ties within a
    tier without letting a well-placed unstarred site outrank a starred one.
    """
    if rank < 1:
        return 0.0
    return 0.4 / rank

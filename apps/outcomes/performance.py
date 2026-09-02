"""Historical Performance aggregation (PRD S42, S57-58). Pure functions --
given a list of already-gathered outcome records, never queried here (see
apps/outcomes/services.py).

Scope note, stated plainly: PRD S42 lists eight breakdown dimensions
(narrative, token age, market-cap range, liquidity range, score range,
smart-money activity, time of day, market conditions). This implements
three -- narrative, token age, and score -- the ones with a clean, already-
available signal to group by. The other five would need either data this
project doesn't track yet at alert time (market conditions has no defined
metric anywhere in the codebase) or a noticeably heavier join for
comparatively little value while real outcome data is still this sparse.
Flagging this as a scope decision, not a silent gap.

"False positive rate" has no PRD-given formula. Defined here as: of alerts
whose tracking is COMPLETE (24h elapsed), the percentage that never reached
2x -- the primary target threshold (PRD S25's own probability ordering:
2x, then 3x, then 5x).
"""

from dataclasses import dataclass
from decimal import Decimal
from statistics import median

# PRD S15's own token-age lifecycle buckets, reused here for breakdown
# grouping rather than inventing a different set of boundaries.
AGE_BUCKET_ORDER = ("0-5m", "5-30m", "30m-3h", "3h+")
SCORE_BUCKET_ORDER = ("0-20", "21-40", "41-60", "61-80", "81-100", "Unknown")


def age_bucket_for(age_seconds: float) -> str:
    if age_seconds < 300:
        return "0-5m"
    if age_seconds < 1800:
        return "5-30m"
    if age_seconds < 10_800:
        return "30m-3h"
    return "3h+"


def score_bucket_for(score: Decimal | None) -> str:
    if score is None:
        return "Unknown"
    if score <= 20:
        return "0-20"
    if score <= 40:
        return "21-40"
    if score <= 60:
        return "41-60"
    if score <= 80:
        return "61-80"
    return "81-100"


@dataclass(frozen=True)
class OutcomeRecord:
    """One outcome's summary, as pulled from TokenOutcome + its Alert/token
    for breakdown grouping. Deliberately not the Django model -- pure
    functions never touch the ORM."""

    reached_2x: bool
    reached_3x: bool
    reached_5x: bool
    max_multiple: Decimal | None
    time_to_2x_seconds: float | None
    time_to_3x_seconds: float | None
    tracking_complete: bool
    narrative_name: str | None
    age_bucket: str
    score_bucket: str


@dataclass
class PerformanceSummary:
    total_signals: int
    completed_signals: int
    hit_rate_2x_pct: Decimal | None = None
    hit_rate_3x_pct: Decimal | None = None
    hit_rate_5x_pct: Decimal | None = None
    avg_multiple: Decimal | None = None
    median_multiple: Decimal | None = None
    max_multiple: Decimal | None = None
    avg_time_to_2x_seconds: int | None = None
    avg_time_to_3x_seconds: int | None = None
    false_positive_rate_pct: Decimal | None = None


@dataclass(frozen=True)
class BreakdownGroup:
    label: str
    total_signals: int
    hit_rate_2x_pct: Decimal | None
    hit_rate_3x_pct: Decimal | None


def _pct(numerator: int, denominator: int) -> Decimal | None:
    if denominator == 0:
        return None
    return (Decimal(numerator) / Decimal(denominator) * 100).quantize(Decimal("0.01"))


def compute_summary(records: list[OutcomeRecord]) -> PerformanceSummary:
    completed = [r for r in records if r.tracking_complete]
    completed_count = len(completed)

    multiples = [r.max_multiple for r in completed if r.max_multiple is not None]
    times_2x = [r.time_to_2x_seconds for r in completed if r.time_to_2x_seconds is not None]
    times_3x = [r.time_to_3x_seconds for r in completed if r.time_to_3x_seconds is not None]

    reached_2x_count = sum(1 for r in completed if r.reached_2x)
    reached_3x_count = sum(1 for r in completed if r.reached_3x)
    reached_5x_count = sum(1 for r in completed if r.reached_5x)
    false_positive_count = sum(1 for r in completed if not r.reached_2x)

    return PerformanceSummary(
        total_signals=len(records),
        completed_signals=completed_count,
        hit_rate_2x_pct=_pct(reached_2x_count, completed_count),
        hit_rate_3x_pct=_pct(reached_3x_count, completed_count),
        hit_rate_5x_pct=_pct(reached_5x_count, completed_count),
        avg_multiple=(sum(multiples) / len(multiples)).quantize(Decimal("0.0001")) if multiples else None,
        median_multiple=median(multiples) if multiples else None,
        max_multiple=max(multiples) if multiples else None,
        avg_time_to_2x_seconds=round(sum(times_2x) / len(times_2x)) if times_2x else None,
        avg_time_to_3x_seconds=round(sum(times_3x) / len(times_3x)) if times_3x else None,
        false_positive_rate_pct=_pct(false_positive_count, completed_count),
    )


def _grouped(records: list[OutcomeRecord], key_fn) -> dict[str, list[OutcomeRecord]]:
    groups: dict[str, list[OutcomeRecord]] = {}
    for record in records:
        groups.setdefault(key_fn(record), []).append(record)
    return groups


def _breakdown_group(label: str, records: list[OutcomeRecord]) -> BreakdownGroup:
    completed = [r for r in records if r.tracking_complete]
    return BreakdownGroup(
        label=label,
        total_signals=len(records),
        hit_rate_2x_pct=_pct(sum(1 for r in completed if r.reached_2x), len(completed)),
        hit_rate_3x_pct=_pct(sum(1 for r in completed if r.reached_3x), len(completed)),
    )


def compute_breakdown_by_narrative(records: list[OutcomeRecord]) -> list[BreakdownGroup]:
    groups = _grouped(records, lambda r: r.narrative_name or "None")
    result = [_breakdown_group(label, group) for label, group in groups.items()]
    return sorted(result, key=lambda g: g.total_signals, reverse=True)


def compute_breakdown_by_age(records: list[OutcomeRecord]) -> list[BreakdownGroup]:
    groups = _grouped(records, lambda r: r.age_bucket)
    return [_breakdown_group(label, groups[label]) for label in AGE_BUCKET_ORDER if label in groups]


def compute_breakdown_by_score(records: list[OutcomeRecord]) -> list[BreakdownGroup]:
    groups = _grouped(records, lambda r: r.score_bucket)
    return [_breakdown_group(label, groups[label]) for label in SCORE_BUCKET_ORDER if label in groups]

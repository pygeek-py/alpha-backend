"""Historical configuration simulation (PRD S44): "if this configuration had
been active, what would have happened?" Pure functions given a pre-fetched
list of candidate observations.

PRD S44's simulation output includes expected 2x/3x hit rate and
false-positive rate -- those need real alert/outcome history (Batches 10-11)
and are honestly left as None here, not estimated. What this module CAN
answer now, from real TokenScore/liquidity/volume history: how many observed
candidates would have passed a given threshold set, and how alert *volume*
would change -- itself a useful, real answer to "would this make alerts
more or less frequent," and the SimulationResult shape already has the
hit-rate fields ready to populate once that data exists, so this doesn't
need restructuring later.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CandidateSnapshot:
    """One historical scoring observation to evaluate a config against."""

    opportunity_score: Decimal | None = None
    risk_score: Decimal | None = None
    liquidity_usd: Decimal | None = None
    volume_5m_usd: Decimal | None = None
    holder_count: int | None = None


# (candidate attribute, config key, "min" or "max")
_THRESHOLD_CHECKS = (
    ("opportunity_score", "min_opportunity_score", "min"),
    ("risk_score", "max_risk_score", "max"),
    ("liquidity_usd", "min_liquidity_usd", "min"),
    ("volume_5m_usd", "min_volume_5m_usd", "min"),
    ("holder_count", "min_holder_count", "min"),
)


def passes_configuration(candidate: CandidateSnapshot, config: dict) -> bool:
    for attr, config_key, kind in _THRESHOLD_CHECKS:
        threshold = config.get(config_key)
        if threshold is None:
            continue
        value = getattr(candidate, attr)
        if value is None:
            return False  # can't confirm it clears a threshold without the data
        if kind == "min" and value < threshold:
            return False
        if kind == "max" and value > threshold:
            return False
    return True


@dataclass
class SimulationResult:
    total_candidates: int
    passing_count: int
    pass_rate_pct: Decimal
    avg_opportunity_score_passing: Decimal | None
    estimated_alerts_per_day: Decimal | None
    # Not computable without Batches 10-11's alert/outcome history -- always
    # None for now; kept here so consuming this result never needs to
    # change shape once that data exists.
    estimated_2x_hit_rate: Decimal | None = None
    estimated_3x_hit_rate: Decimal | None = None
    estimated_false_positive_rate: Decimal | None = None


def simulate_configuration(
    config: dict, candidates: list[CandidateSnapshot], *, window_days: Decimal | None = None
) -> SimulationResult:
    total = len(candidates)
    if total == 0:
        return SimulationResult(
            total_candidates=0,
            passing_count=0,
            pass_rate_pct=Decimal("0"),
            avg_opportunity_score_passing=None,
            estimated_alerts_per_day=None,
        )

    passing = [c for c in candidates if passes_configuration(c, config)]
    pass_rate = (Decimal(len(passing)) / total * 100).quantize(Decimal("0.01"))

    passing_scores = [c.opportunity_score for c in passing if c.opportunity_score is not None]
    avg_score = None
    if passing_scores:
        avg_score = (sum(passing_scores) / len(passing_scores)).quantize(Decimal("0.01"))

    estimated_per_day = None
    if window_days and window_days > 0:
        estimated_per_day = (Decimal(len(passing)) / window_days).quantize(Decimal("0.01"))

    return SimulationResult(
        total_candidates=total,
        passing_count=len(passing),
        pass_rate_pct=pass_rate,
        avg_opportunity_score_passing=avg_score,
        estimated_alerts_per_day=estimated_per_day,
    )

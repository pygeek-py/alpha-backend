"""Threshold recommendation from historical distributions (PRD S44). Pure
functions -- given a pre-fetched list of observed values, not a queryset;
apps/configuration/services.py does the fetching.

Scope note, stated plainly rather than glossed over: PRD S44 lists historical
*outcomes* and *alert performance* (2x/3x hit rate, false-positive rate) among
what the AI should use. Neither exists yet -- Batch 10 (alert generation) and
Batch 11 (outcome tracking) haven't been built. This module recommends
thresholds from what DOES already exist (TokenScore, TokenSafetyCheck,
liquidity/volume/holder snapshots) using percentile analysis, which is a
real, honest signal ("where do observed tokens actually fall on this
metric"), just not the hit-rate-calibrated recommendation the PRD's fuller
vision describes. "Current market regime" and volatility-based adjustment
are also out of scope for this pass -- no regime classifier exists, and
fabricating one wasn't worth the risk of a confident-sounding but
ungrounded number. Confidence scores throughout are what signal this
honestly to anything consuming these recommendations.
"""

from dataclasses import dataclass, field
from decimal import Decimal

MIN_SAMPLE_SIZE_FOR_ANY_CONFIDENCE = 5
MIN_SAMPLE_SIZE_FOR_FULL_CONFIDENCE = 50


def percentile(values: list[Decimal], pct: int) -> Decimal | None:
    """Linear-interpolation percentile, given already-sorted-or-not values."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]

    rank = (Decimal(pct) / 100) * (len(ordered) - 1)
    lower_index = int(rank)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = rank - lower_index
    return ordered[lower_index] + (ordered[upper_index] - ordered[lower_index]) * fraction


@dataclass
class ThresholdRecommendation:
    field_name: str
    current_value: Decimal
    recommended_value: Decimal
    confidence: Decimal
    sample_size: int
    evidence_sufficient: bool
    reason: str


def recommend_threshold(
    *,
    field_name: str,
    values: list[Decimal],
    current_value: Decimal,
    target_percentile: int,
    min_change_to_matter: Decimal = Decimal("0"),
) -> ThresholdRecommendation:
    """Recommends a value at `target_percentile` of the observed distribution.
    For a MINIMUM-style gate (min_liquidity, min_opportunity_score, ...), a
    high target_percentile (e.g. 75) keeps only the strongest quarter of
    observed candidates, matching PRD S6's "quality > quantity" funnel
    philosophy. For a MAXIMUM-style gate (max_risk_score), callers should
    pass a low target_percentile instead.

    With too few observations, recommends keeping the current value
    unchanged rather than overreacting to a tiny, unrepresentative sample --
    `evidence_sufficient=False` signals that plainly to the caller.
    """
    sample_size = len(values)
    if sample_size < MIN_SAMPLE_SIZE_FOR_ANY_CONFIDENCE:
        return ThresholdRecommendation(
            field_name=field_name,
            current_value=current_value,
            recommended_value=current_value,
            confidence=Decimal("0"),
            sample_size=sample_size,
            evidence_sufficient=False,
            reason=f"Only {sample_size} observations -- not enough to recommend a change",
        )

    recommended = percentile(values, target_percentile)
    confidence = min(
        Decimal("100"), Decimal(sample_size) / MIN_SAMPLE_SIZE_FOR_FULL_CONFIDENCE * 100
    ).quantize(Decimal("0.01"))

    change = abs(recommended - current_value)
    if change < min_change_to_matter:
        return ThresholdRecommendation(
            field_name=field_name,
            current_value=current_value,
            recommended_value=current_value,
            confidence=confidence,
            sample_size=sample_size,
            evidence_sufficient=True,
            reason=f"Current value is already close to the {target_percentile}th percentile "
            f"of {sample_size} observations",
        )

    direction = "raise" if recommended > current_value else "lower"
    return ThresholdRecommendation(
        field_name=field_name,
        current_value=current_value,
        recommended_value=recommended,
        confidence=confidence,
        sample_size=sample_size,
        evidence_sufficient=True,
        reason=f"{target_percentile}th percentile of {sample_size} observations suggests "
        f"{direction}ing from {current_value} to {recommended}",
    )


@dataclass
class ConfigurationRecommendationReport:
    thresholds: dict[str, ThresholdRecommendation] = field(default_factory=dict)
    overall_confidence: Decimal = Decimal("0")
    notes: list[str] = field(default_factory=list)


def build_recommendation_report(
    thresholds: dict[str, ThresholdRecommendation],
) -> ConfigurationRecommendationReport:
    if not thresholds:
        return ConfigurationRecommendationReport(notes=["No thresholds evaluated"])

    confidences = [t.confidence for t in thresholds.values()]
    overall = (sum(confidences) / len(confidences)).quantize(Decimal("0.01"))

    notes = [
        f"{name}: {t.reason}"
        for name, t in thresholds.items()
        if not t.evidence_sufficient
    ]

    return ConfigurationRecommendationReport(
        thresholds=thresholds, overall_confidence=overall, notes=notes
    )

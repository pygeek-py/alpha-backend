"""Rule-based Prediction Engine (PRD S25, S49). Deterministic and fully
explainable by construction -- no training required (ARCHITECTURE.md S8: "no
training required, fully explainable by construction"; the PRD explicitly
warns the initial version should NOT depend heavily on machine learning).

Pure functions -- every input is an already-computed TokenScore row or plain
value, never queried here (see apps/predictions/services.py for that).
"""

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

# 5X: the hardest target. Weighted even more toward safety and sustained
# wallet/narrative conviction, and even less toward short-lived momentum and
# buy-pressure, than apps/scoring/engine.py's SCORE_3X_WEIGHTS -- reaching 5x
# needs a real story that smart money keeps believing, not just an early
# pump. Deliberately kept local to this app rather than added to the Scoring
# Engine (Batch 8, already complete): the Prediction Engine is free to
# combine Scoring's per-category outputs its own way, per the PRD's own
# Scoring -> Prediction pipeline separation.
SCORE_5X_WEIGHTS = {
    "safety": Decimal("25"),
    "liquidity": Decimal("10"),
    "momentum": Decimal("8"),
    "holder_growth": Decimal("12"),
    "wallet": Decimal("20"),
    "buy_pressure": Decimal("3"),
    "price_structure": Decimal("2"),
    "narrative": Decimal("15"),
    "creator_history": Decimal("5"),
}
assert sum(SCORE_5X_WEIGHTS.values()) == 100

# TokenScore field name -> SCORE_5X_WEIGHTS key.
_CATEGORY_FIELD_WEIGHT_KEYS = {
    "safety_score": "safety",
    "liquidity_score": "liquidity",
    "momentum_score": "momentum",
    "holder_growth_score": "holder_growth",
    "wallet_score": "wallet",
    "buy_pressure_score": "buy_pressure",
    "price_structure_score": "price_structure",
    "narrative_score": "narrative",
    "creator_score": "creator_history",
}


def compute_score_5x(token_score) -> Decimal | None:
    """Weighted aggregate over TokenScore's already-computed category
    sub-scores (Batch 8), using SCORE_5X_WEIGHTS. Renormalizes over whatever
    categories have real data -- same principle as apps/scoring/engine.py's
    aggregator. None only when NO category has any data at all."""
    weighted_sum = Decimal("0")
    total_weight = Decimal("0")
    for field_name, weight_key in _CATEGORY_FIELD_WEIGHT_KEYS.items():
        value = getattr(token_score, field_name)
        if value is None:
            continue
        weight = SCORE_5X_WEIGHTS[weight_key]
        weighted_sum += value * weight
        total_weight += weight

    if total_weight == 0:
        return None
    return (weighted_sum / total_weight).quantize(Decimal("0.01"))


def score_to_probability(score: Decimal | None) -> Decimal:
    """PRD S25: rule-based scoring first, no training required. The
    deterministic 0-100 score IS the V1 probability estimate -- direct and
    explainable by construction. Bounded to [0, 100] before conversion in
    case an upstream category aggregate ever drifts outside range."""
    if score is None:
        return Decimal("0.0000")
    bounded = max(Decimal("0"), min(Decimal("100"), score))
    return (bounded / 100).quantize(Decimal("0.0001"))


@dataclass
class PredictionResult:
    probability_2x: Decimal
    probability_3x: Decimal
    probability_5x: Decimal
    risk_probability: Decimal
    expected_time_to_target: timedelta | None
    feature_snapshot: dict = field(default_factory=dict)


def _str_or_none(value) -> str | None:
    return str(value) if value is not None else None


def compute_prediction(
    *,
    token_score,
    current_market_cap: Decimal | None,
    historical_median_time_to_2x: timedelta | None,
) -> PredictionResult:
    """The rule-based prediction for one TokenScore observation.

    `historical_median_time_to_2x` is the one place this V1 engine reaches
    for real outcome history (Batch 11) rather than a fixed rule: PRD S28's
    principle is to learn from what actually happened, so once real
    TokenOutcome data exists, `expected_time_to_target` reflects it. Until
    then it's honestly None -- never a fabricated guess.
    """
    score_5x = compute_score_5x(token_score)

    target_market_caps = {}
    if current_market_cap is not None:
        target_market_caps = {
            "target_market_cap_2x": str(current_market_cap * 2),
            "target_market_cap_3x": str(current_market_cap * 3),
            "target_market_cap_5x": str(current_market_cap * 5),
        }

    feature_snapshot = {
        "opportunity_score": str(token_score.opportunity_score),
        "risk_score": str(token_score.risk_score),
        "score_2x": str(token_score.score_2x),
        "score_3x": str(token_score.score_3x),
        "score_5x": _str_or_none(score_5x),
        "explanation": token_score.explanation,
        "current_market_cap": _str_or_none(current_market_cap),
        "historical_time_to_2x_basis": _str_or_none(historical_median_time_to_2x),
        **target_market_caps,
    }

    return PredictionResult(
        probability_2x=score_to_probability(token_score.score_2x),
        probability_3x=score_to_probability(token_score.score_3x),
        probability_5x=score_to_probability(score_5x),
        risk_probability=score_to_probability(token_score.risk_score),
        expected_time_to_target=historical_median_time_to_2x,
        feature_snapshot=feature_snapshot,
    )

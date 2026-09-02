from datetime import timedelta
from statistics import median

from django.utils import timezone

from apps.outcomes.models import TokenOutcome
from apps.predictions.models import Prediction
from apps.predictions.rules import compute_prediction
from apps.tokens.models import Token


def historical_median_time_to_2x() -> timedelta | None:
    """Real-world grounding from Batch 11's outcome data, once it exists
    (PRD S28: learn from what actually happened, never fabricate). None,
    honestly, until at least one token has actually reached 2x."""
    durations = TokenOutcome.objects.filter(
        reached_2x=True, time_to_2x__isnull=False
    ).values_list("time_to_2x", flat=True)
    seconds = sorted(d.total_seconds() for d in durations)
    if not seconds:
        return None
    return timedelta(seconds=median(seconds))


def generate_prediction(token: Token) -> Prediction | None:
    """Runs the rule-based Prediction Engine for `token` and persists the
    result. Returns None if there's no TokenScore yet -- nothing to predict
    from (Scoring runs before Prediction in the pipeline -- PRD S9)."""
    token_score = token.scores.order_by("-timestamp").first()
    if token_score is None:
        return None

    latest_snapshot = token.snapshots.order_by("-timestamp").first()
    current_market_cap = latest_snapshot.market_cap if latest_snapshot else None

    result = compute_prediction(
        token_score=token_score,
        current_market_cap=current_market_cap,
        historical_median_time_to_2x=historical_median_time_to_2x(),
    )

    return Prediction.objects.create(
        token=token,
        timestamp=timezone.now(),
        probability_2x=result.probability_2x,
        probability_3x=result.probability_3x,
        probability_5x=result.probability_5x,
        risk_probability=result.risk_probability,
        expected_time_to_target=result.expected_time_to_target,
        feature_snapshot=result.feature_snapshot,
    )

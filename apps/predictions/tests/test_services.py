from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.alerts.models import Alert, AlertState
from apps.market_data.models import TokenSnapshot
from apps.outcomes.models import TokenOutcome
from apps.predictions.models import Prediction
from apps.predictions.services import generate_prediction, historical_median_time_to_2x
from apps.scoring.models import TokenScore
from apps.tokens.factories import TokenFactory


def _score(token, **overrides):
    defaults = {
        "opportunity_score": Decimal("65"),
        "risk_score": Decimal("25"),
        "score_2x": Decimal("70"),
        "score_3x": Decimal("55"),
        "safety_score": Decimal("80"),
    }
    defaults.update(overrides)
    return TokenScore.objects.create(token=token, timestamp=timezone.now(), **defaults)


@pytest.mark.django_db
class TestGeneratePrediction:
    def test_no_token_score_returns_none(self):
        token = TokenFactory()
        assert generate_prediction(token) is None
        assert Prediction.objects.count() == 0

    def test_creates_a_prediction_from_the_latest_score(self):
        token = TokenFactory()
        _score(token, score_2x=Decimal("80"), score_3x=Decimal("60"))

        prediction = generate_prediction(token)

        assert prediction is not None
        assert prediction.probability_2x == Decimal("0.8000")
        assert prediction.probability_3x == Decimal("0.6000")
        assert prediction.token_id == token.id

    def test_uses_the_most_recent_score_when_several_exist(self):
        token = TokenFactory()
        now = timezone.now()
        TokenScore.objects.create(
            token=token, timestamp=now - timedelta(minutes=5), opportunity_score=Decimal("65"),
            risk_score=Decimal("25"), score_2x=Decimal("10"), score_3x=Decimal("55"),
        )
        TokenScore.objects.create(
            token=token, timestamp=now, opportunity_score=Decimal("65"),
            risk_score=Decimal("25"), score_2x=Decimal("90"), score_3x=Decimal("55"),
        )

        prediction = generate_prediction(token)

        assert prediction.probability_2x == Decimal("0.9000")

    def test_feature_snapshot_includes_current_market_cap(self):
        token = TokenFactory()
        _score(token)
        TokenSnapshot.objects.create(
            token=token, timestamp=timezone.now(), price=Decimal("0.001"), market_cap=Decimal("50000")
        )

        prediction = generate_prediction(token)

        assert prediction.feature_snapshot["current_market_cap"] == "50000.000000"
        assert prediction.feature_snapshot["target_market_cap_2x"] == "100000.000000"


@pytest.mark.django_db
class TestHistoricalMedianTimeTo2x:
    def test_no_outcomes_returns_none(self):
        assert historical_median_time_to_2x() is None

    def test_ignores_outcomes_that_never_reached_2x(self):
        token = TokenFactory()
        alert = Alert.objects.create(token=token, state=AlertState.CONFIRMED, score=Decimal("80"))
        TokenOutcome.objects.create(
            token=token, alert=alert, reference_timestamp=timezone.now(), initial_price="1",
            reached_2x=False,
        )
        assert historical_median_time_to_2x() is None

    def test_computes_the_median_across_reached_outcomes(self):
        durations = [timedelta(minutes=10), timedelta(minutes=20), timedelta(minutes=60)]
        for duration in durations:
            token = TokenFactory()
            alert = Alert.objects.create(token=token, state=AlertState.CONFIRMED, score=Decimal("80"))
            TokenOutcome.objects.create(
                token=token, alert=alert, reference_timestamp=timezone.now(), initial_price="1",
                reached_2x=True, time_to_2x=duration,
            )

        assert historical_median_time_to_2x() == timedelta(minutes=20)

    def test_feeds_into_generate_prediction_expected_time_to_target(self):
        token = TokenFactory()
        alert = Alert.objects.create(token=token, state=AlertState.CONFIRMED, score=Decimal("80"))
        TokenOutcome.objects.create(
            token=token, alert=alert, reference_timestamp=timezone.now(), initial_price="1",
            reached_2x=True, time_to_2x=timedelta(minutes=15),
        )

        other_token = TokenFactory()
        _score(other_token)
        prediction = generate_prediction(other_token)

        assert prediction.expected_time_to_target == timedelta(minutes=15)

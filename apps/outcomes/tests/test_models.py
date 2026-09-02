import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.alerts.factories import AlertFactory
from apps.outcomes.models import TokenOutcome, TokenOutcomeSnapshot


@pytest.mark.django_db
class TestTokenOutcome:
    def test_one_outcome_per_alert(self):
        alert = AlertFactory()
        TokenOutcome.objects.create(
            token=alert.token,
            alert=alert,
            reference_timestamp=timezone.now(),
            initial_price="0.001",
        )
        with pytest.raises(IntegrityError):
            TokenOutcome.objects.create(
                token=alert.token,
                alert=alert,
                reference_timestamp=timezone.now(),
                initial_price="0.002",
            )

    def test_prediction_is_optional(self):
        alert = AlertFactory()
        outcome = TokenOutcome.objects.create(
            token=alert.token,
            alert=alert,
            reference_timestamp=timezone.now(),
            initial_price="0.001",
        )
        assert outcome.prediction is None

    def test_defaults(self):
        alert = AlertFactory()
        outcome = TokenOutcome.objects.create(
            token=alert.token,
            alert=alert,
            reference_timestamp=timezone.now(),
            initial_price="0.001",
        )
        assert outcome.reached_2x is False
        assert outcome.tracking_complete is False


@pytest.mark.django_db
class TestTokenOutcomeSnapshot:
    def test_unique_offset_per_outcome(self):
        alert = AlertFactory()
        outcome = TokenOutcome.objects.create(
            token=alert.token,
            alert=alert,
            reference_timestamp=timezone.now(),
            initial_price="0.001",
        )
        TokenOutcomeSnapshot.objects.create(
            outcome=outcome, offset_label=TokenOutcomeSnapshot.Offset.M5, recorded_at=timezone.now()
        )
        with pytest.raises(IntegrityError):
            TokenOutcomeSnapshot.objects.create(
                outcome=outcome, offset_label=TokenOutcomeSnapshot.Offset.M5, recorded_at=timezone.now()
            )

    def test_related_name(self):
        alert = AlertFactory()
        outcome = TokenOutcome.objects.create(
            token=alert.token,
            alert=alert,
            reference_timestamp=timezone.now(),
            initial_price="0.001",
        )
        TokenOutcomeSnapshot.objects.create(
            outcome=outcome, offset_label=TokenOutcomeSnapshot.Offset.M10, recorded_at=timezone.now()
        )
        assert outcome.snapshots.count() == 1

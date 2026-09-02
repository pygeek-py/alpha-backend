import itertools
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.alerts.models import Alert, AlertState
from apps.holders.models import HolderSnapshot
from apps.liquidity.models import LiquiditySnapshot
from apps.market_data.models import TokenSnapshot
from apps.outcomes.models import TokenOutcome, TokenOutcomeSnapshot
from apps.outcomes.services import create_missing_outcomes, record_due_snapshots, sweep_due_outcomes
from apps.predictions.factories import PredictionFactory
from apps.tokens.factories import TokenFactory

_timestamp_counter = itertools.count()


def _next_timestamp():
    return timezone.now() + timedelta(seconds=next(_timestamp_counter))


def _alert(*, state=AlertState.CONFIRMED, token=None):
    token = token or TokenFactory()
    return Alert.objects.create(token=token, state=state, score=Decimal("80"))


def _price_snapshot(token, *, when, price):
    TokenSnapshot.objects.create(token=token, timestamp=when, price=price)


@pytest.mark.django_db
class TestCreateMissingOutcomes:
    def test_no_alerts_creates_nothing(self):
        assert create_missing_outcomes() == []

    def test_watching_alerts_are_not_tracked(self):
        alert = _alert(state=AlertState.WATCHING)
        _price_snapshot(alert.token, when=alert.created_at, price=Decimal("0.001"))
        assert create_missing_outcomes() == []

    def test_confirmed_alert_without_a_price_snapshot_is_skipped(self):
        _alert(state=AlertState.CONFIRMED)
        assert create_missing_outcomes() == []
        assert TokenOutcome.objects.count() == 0

    def test_confirmed_alert_with_a_price_snapshot_starts_tracking(self):
        alert = _alert(state=AlertState.CONFIRMED)
        _price_snapshot(alert.token, when=alert.created_at, price=Decimal("0.001"))

        created = create_missing_outcomes()

        assert len(created) == 1
        outcome = created[0]
        assert outcome.alert_id == alert.id
        assert outcome.token_id == alert.token_id
        assert outcome.initial_price == Decimal("0.001")

    def test_is_idempotent(self):
        alert = _alert(state=AlertState.CONFIRMED)
        _price_snapshot(alert.token, when=alert.created_at, price=Decimal("0.001"))
        create_missing_outcomes()
        assert create_missing_outcomes() == []
        assert TokenOutcome.objects.count() == 1

    def test_backfills_the_alert_prediction_onto_the_outcome(self):
        alert = _alert(state=AlertState.CONFIRMED)
        prediction = PredictionFactory(token=alert.token)
        Alert.objects.filter(pk=alert.pk).update(prediction=prediction)
        alert.refresh_from_db()
        _price_snapshot(alert.token, when=alert.created_at, price=Decimal("0.001"))

        created = create_missing_outcomes()

        assert created[0].prediction_id == prediction.id

    def test_leaves_prediction_none_when_the_alert_has_none(self):
        alert = _alert(state=AlertState.CONFIRMED)
        _price_snapshot(alert.token, when=alert.created_at, price=Decimal("0.001"))

        created = create_missing_outcomes()

        assert created[0].prediction is None

    def test_uses_the_snapshot_at_or_before_alert_time_not_a_later_one(self):
        alert = _alert(state=AlertState.CONFIRMED)
        _price_snapshot(alert.token, when=alert.created_at - timedelta(minutes=1), price=Decimal("0.001"))
        _price_snapshot(alert.token, when=alert.created_at + timedelta(minutes=1), price=Decimal("999"))

        created = create_missing_outcomes()

        assert created[0].initial_price == Decimal("0.001")


@pytest.mark.django_db
class TestRecordDueSnapshots:
    def _tracked_outcome(self):
        alert = _alert(state=AlertState.CONFIRMED)
        _price_snapshot(alert.token, when=alert.created_at, price=Decimal("1.00"))
        return create_missing_outcomes()[0]

    def test_nothing_due_yet_records_nothing(self):
        outcome = self._tracked_outcome()
        assert record_due_snapshots(outcome) == []

    def test_5m_offset_recorded_once_due(self):
        outcome = self._tracked_outcome()
        outcome.reference_timestamp = timezone.now() - timedelta(minutes=6)
        outcome.save()

        snapshots = record_due_snapshots(outcome)

        assert [s.offset_label for s in snapshots] == ["5m"]
        assert TokenOutcomeSnapshot.objects.filter(outcome=outcome).count() == 1

    def test_recording_twice_does_not_duplicate(self):
        outcome = self._tracked_outcome()
        outcome.reference_timestamp = timezone.now() - timedelta(minutes=6)
        outcome.save()

        record_due_snapshots(outcome)
        second_pass = record_due_snapshots(outcome)

        assert second_pass == []
        assert TokenOutcomeSnapshot.objects.filter(outcome=outcome).count() == 1

    def test_snapshot_pulls_point_in_time_liquidity_and_holders(self):
        outcome = self._tracked_outcome()
        outcome.reference_timestamp = timezone.now() - timedelta(minutes=6)
        outcome.save()
        due_at = outcome.reference_timestamp + timedelta(minutes=5)
        LiquiditySnapshot.objects.create(
            token=outcome.token, timestamp=due_at - timedelta(seconds=1), liquidity_usd=Decimal("50000")
        )
        HolderSnapshot.objects.create(
            token=outcome.token, timestamp=due_at - timedelta(seconds=1), holder_count=300
        )

        snapshots = record_due_snapshots(outcome)

        assert snapshots[0].liquidity_usd == Decimal("50000")
        assert snapshots[0].holder_count == 300

    def test_labels_update_when_price_crosses_2x(self):
        outcome = self._tracked_outcome()
        outcome.reference_timestamp = timezone.now() - timedelta(minutes=6)
        outcome.save()
        _price_snapshot(
            outcome.token, when=outcome.reference_timestamp + timedelta(minutes=3), price=Decimal("2.50")
        )

        record_due_snapshots(outcome)
        outcome.refresh_from_db()

        assert outcome.reached_2x is True
        assert outcome.max_multiple == Decimal("2.5000")

    def test_tracking_marked_complete_once_24h_offset_recorded(self):
        outcome = self._tracked_outcome()
        outcome.reference_timestamp = timezone.now() - timedelta(hours=25)
        outcome.save()

        record_due_snapshots(outcome)
        outcome.refresh_from_db()

        assert outcome.tracking_complete is True
        assert TokenOutcomeSnapshot.objects.filter(outcome=outcome).count() == 9


@pytest.mark.django_db
class TestSweepDueOutcomes:
    def test_starts_tracking_and_records_due_offsets_in_one_pass(self):
        alert = _alert(state=AlertState.CONFIRMED)
        past = timezone.now() - timedelta(minutes=6)
        _price_snapshot(alert.token, when=past, price=Decimal("1.00"))

        # Backdate the alert itself so the new outcome's reference_timestamp is in the past.
        Alert.objects.filter(pk=alert.pk).update(created_at=past)

        result = sweep_due_outcomes()

        assert result["outcomes_started"] == 1
        assert result["snapshots_recorded"] == 1
        outcome = TokenOutcome.objects.get(alert=alert)
        assert outcome.snapshots.count() == 1

    def test_completed_outcomes_are_not_swept_again(self):
        alert = _alert(state=AlertState.CONFIRMED)
        far_past = timezone.now() - timedelta(hours=25)
        _price_snapshot(alert.token, when=far_past, price=Decimal("1.00"))
        Alert.objects.filter(pk=alert.pk).update(created_at=far_past)

        first = sweep_due_outcomes()
        second = sweep_due_outcomes()

        assert first["outcomes_completed"] == 1
        assert second["outcomes_started"] == 0
        assert second["snapshots_recorded"] == 0

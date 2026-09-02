from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal

from apps.outcomes.tracking import (
    PricePoint,
    compute_due_offsets,
    compute_outcome_labels,
    compute_price_extremes,
    is_tracking_complete,
)

REF = datetime(2026, 1, 1, tzinfo=dt_timezone.utc)


class TestComputeDueOffsets:
    def test_nothing_due_immediately(self):
        due = compute_due_offsets(reference_timestamp=REF, now=REF, already_recorded=set())
        assert due == []

    def test_5m_due_after_5_minutes(self):
        due = compute_due_offsets(
            reference_timestamp=REF, now=REF + timedelta(minutes=5), already_recorded=set()
        )
        assert due == ["5m"]

    def test_multiple_offsets_due_at_once(self):
        due = compute_due_offsets(
            reference_timestamp=REF, now=REF + timedelta(minutes=31), already_recorded=set()
        )
        assert due == ["5m", "10m", "15m", "30m"]

    def test_already_recorded_offsets_are_excluded(self):
        due = compute_due_offsets(
            reference_timestamp=REF, now=REF + timedelta(minutes=31), already_recorded={"5m", "10m"}
        )
        assert due == ["15m", "30m"]

    def test_all_offsets_due_after_24h(self):
        due = compute_due_offsets(
            reference_timestamp=REF, now=REF + timedelta(hours=25), already_recorded=set()
        )
        assert due == ["5m", "10m", "15m", "30m", "1h", "3h", "6h", "12h", "24h"]


class TestComputePriceExtremes:
    def test_no_price_points_returns_empty(self):
        extremes = compute_price_extremes(initial_price=Decimal("1"), price_points=[])
        assert extremes.max_multiple is None

    def test_no_initial_price_returns_empty(self):
        points = [PricePoint(timestamp=REF, price=Decimal("2"))]
        extremes = compute_price_extremes(initial_price=None, price_points=points)
        assert extremes.max_multiple is None

    def test_peak_and_trough_multiples(self):
        points = [
            PricePoint(timestamp=REF, price=Decimal("1")),
            PricePoint(timestamp=REF, price=Decimal("3")),
            PricePoint(timestamp=REF, price=Decimal("0.5")),
        ]
        extremes = compute_price_extremes(initial_price=Decimal("1"), price_points=points)
        assert extremes.max_multiple == Decimal("3.0000")
        assert extremes.max_gain_pct == Decimal("200.00")
        assert extremes.max_drawdown_pct == Decimal("-50.00")


class TestComputeOutcomeLabels:
    def test_no_data_gives_no_labels(self):
        labels = compute_outcome_labels(initial_price=Decimal("1"), reference_timestamp=REF, price_points=[])
        assert labels.max_multiple is None
        assert labels.reached_2x is False

    def test_reaches_2x_but_not_3x(self):
        points = [PricePoint(timestamp=REF + timedelta(minutes=10), price=Decimal("2.5"))]
        labels = compute_outcome_labels(
            initial_price=Decimal("1"), reference_timestamp=REF, price_points=points
        )
        assert labels.reached_1_5x is True
        assert labels.reached_2x is True
        assert labels.reached_3x is False
        assert labels.reached_5x is False
        assert labels.time_to_2x == timedelta(minutes=10)
        assert labels.time_to_3x is None

    def test_time_to_target_is_the_first_crossing(self):
        points = [
            PricePoint(timestamp=REF + timedelta(minutes=5), price=Decimal("1.2")),
            PricePoint(timestamp=REF + timedelta(minutes=10), price=Decimal("2.1")),
            PricePoint(timestamp=REF + timedelta(minutes=20), price=Decimal("2.5")),
        ]
        labels = compute_outcome_labels(
            initial_price=Decimal("1"), reference_timestamp=REF, price_points=points
        )
        assert labels.time_to_2x == timedelta(minutes=10)

    def test_unordered_points_are_sorted_before_finding_first_crossing(self):
        points = [
            PricePoint(timestamp=REF + timedelta(minutes=20), price=Decimal("2.5")),
            PricePoint(timestamp=REF + timedelta(minutes=10), price=Decimal("2.1")),
        ]
        labels = compute_outcome_labels(
            initial_price=Decimal("1"), reference_timestamp=REF, price_points=points
        )
        assert labels.time_to_2x == timedelta(minutes=10)

    def test_reaches_10x(self):
        points = [PricePoint(timestamp=REF + timedelta(hours=1), price=Decimal("12"))]
        labels = compute_outcome_labels(
            initial_price=Decimal("1"), reference_timestamp=REF, price_points=points
        )
        assert labels.reached_10x is True
        assert labels.max_multiple == Decimal("12.0000")

    def test_drawdown_only_never_reaches_any_threshold(self):
        points = [PricePoint(timestamp=REF + timedelta(minutes=5), price=Decimal("0.3"))]
        labels = compute_outcome_labels(
            initial_price=Decimal("1"), reference_timestamp=REF, price_points=points
        )
        assert labels.reached_1_5x is False
        assert labels.max_drawdown_pct == Decimal("-70.00")


class TestIsTrackingComplete:
    def test_incomplete_without_24h(self):
        assert is_tracking_complete(recorded_offsets={"5m", "10m", "12h"}) is False

    def test_complete_with_24h(self):
        assert is_tracking_complete(recorded_offsets={"5m", "24h"}) is True

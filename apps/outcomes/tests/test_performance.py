from decimal import Decimal

from apps.outcomes.performance import (
    OutcomeRecord,
    age_bucket_for,
    compute_breakdown_by_age,
    compute_breakdown_by_narrative,
    compute_breakdown_by_score,
    compute_summary,
    score_bucket_for,
)


def _record(**overrides) -> OutcomeRecord:
    defaults = dict(
        reached_2x=False,
        reached_3x=False,
        reached_5x=False,
        max_multiple=None,
        time_to_2x_seconds=None,
        time_to_3x_seconds=None,
        tracking_complete=True,
        narrative_name=None,
        age_bucket="0-5m",
        score_bucket="81-100",
    )
    defaults.update(overrides)
    return OutcomeRecord(**defaults)


class TestAgeBucketFor:
    def test_under_5_minutes(self):
        assert age_bucket_for(60) == "0-5m"

    def test_boundary_5_minutes_moves_to_next_bucket(self):
        assert age_bucket_for(300) == "5-30m"

    def test_30_minutes_to_3_hours(self):
        assert age_bucket_for(3600) == "30m-3h"

    def test_over_3_hours(self):
        assert age_bucket_for(20_000) == "3h+"


class TestScoreBucketFor:
    def test_none_is_unknown(self):
        assert score_bucket_for(None) == "Unknown"

    def test_zero(self):
        assert score_bucket_for(Decimal("0")) == "0-20"

    def test_boundary_is_inclusive(self):
        assert score_bucket_for(Decimal("20")) == "0-20"
        assert score_bucket_for(Decimal("21")) == "21-40"

    def test_top_bucket(self):
        assert score_bucket_for(Decimal("95")) == "81-100"


class TestComputeSummary:
    def test_no_records(self):
        summary = compute_summary([])
        assert summary.total_signals == 0
        assert summary.completed_signals == 0
        assert summary.hit_rate_2x_pct is None
        assert summary.avg_multiple is None

    def test_incomplete_tracking_excluded_from_rates(self):
        records = [_record(tracking_complete=False, reached_2x=True)]
        summary = compute_summary(records)
        assert summary.total_signals == 1
        assert summary.completed_signals == 0
        assert summary.hit_rate_2x_pct is None

    def test_hit_rates(self):
        records = [
            _record(reached_2x=True, reached_3x=True),
            _record(reached_2x=True, reached_3x=False),
            _record(reached_2x=False, reached_3x=False),
            _record(reached_2x=False, reached_3x=False),
        ]
        summary = compute_summary(records)
        assert summary.hit_rate_2x_pct == Decimal("50.00")
        assert summary.hit_rate_3x_pct == Decimal("25.00")

    def test_false_positive_rate_is_never_reaching_2x(self):
        records = [
            _record(reached_2x=True),
            _record(reached_2x=False),
            _record(reached_2x=False),
        ]
        summary = compute_summary(records)
        assert summary.false_positive_rate_pct == Decimal("66.67")

    def test_multiple_stats(self):
        records = [
            _record(max_multiple=Decimal("1.5")),
            _record(max_multiple=Decimal("2.5")),
            _record(max_multiple=Decimal("4.0")),
        ]
        summary = compute_summary(records)
        assert summary.avg_multiple == Decimal("2.6667")
        assert summary.median_multiple == Decimal("2.5")
        assert summary.max_multiple == Decimal("4.0")

    def test_avg_time_to_target(self):
        records = [
            _record(time_to_2x_seconds=600.0),
            _record(time_to_2x_seconds=1200.0),
        ]
        summary = compute_summary(records)
        assert summary.avg_time_to_2x_seconds == 900

    def test_no_multiples_leaves_stats_none_not_zero(self):
        records = [_record(max_multiple=None)]
        summary = compute_summary(records)
        assert summary.avg_multiple is None
        assert summary.median_multiple is None
        assert summary.max_multiple is None


class TestBreakdownByNarrative:
    def test_groups_by_narrative_name(self):
        records = [
            _record(narrative_name="AI Meme", reached_2x=True),
            _record(narrative_name="AI Meme", reached_2x=False),
            _record(narrative_name="Animal Meme", reached_2x=True),
        ]
        groups = compute_breakdown_by_narrative(records)
        by_label = {g.label: g for g in groups}
        assert by_label["AI Meme"].total_signals == 2
        assert by_label["AI Meme"].hit_rate_2x_pct == Decimal("50.00")
        assert by_label["Animal Meme"].total_signals == 1

    def test_missing_narrative_groups_as_none(self):
        records = [_record(narrative_name=None)]
        groups = compute_breakdown_by_narrative(records)
        assert groups[0].label == "None"

    def test_sorted_by_signal_count_descending(self):
        records = [
            _record(narrative_name="Small"),
            _record(narrative_name="Big"),
            _record(narrative_name="Big"),
        ]
        groups = compute_breakdown_by_narrative(records)
        assert groups[0].label == "Big"


class TestBreakdownByAge:
    def test_groups_and_orders_by_lifecycle_bucket(self):
        records = [
            _record(age_bucket="3h+"),
            _record(age_bucket="0-5m"),
            _record(age_bucket="30m-3h"),
        ]
        groups = compute_breakdown_by_age(records)
        assert [g.label for g in groups] == ["0-5m", "30m-3h", "3h+"]

    def test_empty_buckets_are_omitted(self):
        records = [_record(age_bucket="0-5m")]
        groups = compute_breakdown_by_age(records)
        assert len(groups) == 1


class TestBreakdownByScore:
    def test_groups_and_orders_by_score_bucket(self):
        records = [
            _record(score_bucket="81-100"),
            _record(score_bucket="0-20"),
            _record(score_bucket="41-60"),
        ]
        groups = compute_breakdown_by_score(records)
        assert [g.label for g in groups] == ["0-20", "41-60", "81-100"]

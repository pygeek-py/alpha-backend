from decimal import Decimal

from apps.configuration.analysis import (
    build_recommendation_report,
    percentile,
    recommend_threshold,
)


class TestPercentile:
    def test_empty_list_is_none(self):
        assert percentile([], 50) is None

    def test_single_value(self):
        assert percentile([Decimal("42")], 75) == Decimal("42")

    def test_median_of_odd_count(self):
        values = [Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4"), Decimal("5")]
        assert percentile(values, 50) == Decimal("3")

    def test_unsorted_input_is_sorted_first(self):
        values = [Decimal("5"), Decimal("1"), Decimal("3"), Decimal("2"), Decimal("4")]
        assert percentile(values, 50) == Decimal("3")

    def test_0th_percentile_is_minimum(self):
        values = [Decimal("10"), Decimal("20"), Decimal("30")]
        assert percentile(values, 0) == Decimal("10")

    def test_100th_percentile_is_maximum(self):
        values = [Decimal("10"), Decimal("20"), Decimal("30")]
        assert percentile(values, 100) == Decimal("30")

    def test_75th_percentile_interpolates(self):
        values = [Decimal("0"), Decimal("100")]
        assert percentile(values, 75) == Decimal("75")


class TestRecommendThreshold:
    def test_insufficient_sample_keeps_current_value(self):
        result = recommend_threshold(
            field_name="min_liquidity_usd",
            values=[Decimal("100"), Decimal("200")],
            current_value=Decimal("50"),
            target_percentile=75,
        )
        assert result.recommended_value == Decimal("50")
        assert result.evidence_sufficient is False
        assert result.confidence == Decimal("0")

    def test_sufficient_sample_recommends_percentile_value(self):
        values = [Decimal(i) for i in range(1, 21)]  # 1..20
        result = recommend_threshold(
            field_name="min_opportunity_score",
            values=values,
            current_value=Decimal("5"),
            target_percentile=50,
        )
        assert result.evidence_sufficient is True
        assert result.recommended_value != result.current_value

    def test_close_current_value_reports_no_meaningful_change(self):
        values = [Decimal("50")] * 20
        result = recommend_threshold(
            field_name="min_opportunity_score",
            values=values,
            current_value=Decimal("50"),
            target_percentile=50,
            min_change_to_matter=Decimal("1"),
        )
        assert result.recommended_value == result.current_value
        assert result.evidence_sufficient is True
        assert "already close" in result.reason

    def test_confidence_scales_with_sample_size(self):
        small = recommend_threshold(
            field_name="x", values=[Decimal(i) for i in range(1, 11)],
            current_value=Decimal("0"), target_percentile=50,
        )
        large = recommend_threshold(
            field_name="x", values=[Decimal(i) for i in range(1, 101)],
            current_value=Decimal("0"), target_percentile=50,
        )
        assert large.confidence > small.confidence

    def test_confidence_caps_at_100(self):
        values = [Decimal(i) for i in range(1, 201)]
        result = recommend_threshold(
            field_name="x", values=values, current_value=Decimal("0"), target_percentile=50
        )
        assert result.confidence == Decimal("100.00")


class TestBuildRecommendationReport:
    def test_empty_thresholds(self):
        report = build_recommendation_report({})
        assert report.notes == ["No thresholds evaluated"]

    def test_overall_confidence_averages_across_fields(self):
        low = recommend_threshold(
            field_name="a", values=[Decimal("1"), Decimal("2")],
            current_value=Decimal("0"), target_percentile=50,
        )
        high = recommend_threshold(
            field_name="b", values=[Decimal(i) for i in range(1, 101)],
            current_value=Decimal("0"), target_percentile=50,
        )
        report = build_recommendation_report({"a": low, "b": high})
        assert Decimal("0") < report.overall_confidence < Decimal("100")

    def test_insufficient_evidence_fields_produce_notes(self):
        low = recommend_threshold(
            field_name="a", values=[Decimal("1")], current_value=Decimal("0"), target_percentile=50
        )
        report = build_recommendation_report({"a": low})
        assert len(report.notes) == 1

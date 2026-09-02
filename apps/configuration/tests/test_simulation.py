from decimal import Decimal

from apps.configuration.simulation import CandidateSnapshot, passes_configuration, simulate_configuration


def _candidate(**overrides) -> CandidateSnapshot:
    defaults = dict(
        opportunity_score=Decimal("80"),
        risk_score=Decimal("20"),
        liquidity_usd=Decimal("50000"),
        volume_5m_usd=Decimal("10000"),
        holder_count=200,
    )
    defaults.update(overrides)
    return CandidateSnapshot(**defaults)


class TestPassesConfiguration:
    def test_empty_config_always_passes(self):
        assert passes_configuration(_candidate(), {}) is True

    def test_passes_when_meets_all_min_thresholds(self):
        config = {"min_opportunity_score": Decimal("50"), "min_liquidity_usd": Decimal("10000")}
        assert passes_configuration(_candidate(), config) is True

    def test_fails_when_below_a_min_threshold(self):
        config = {"min_opportunity_score": Decimal("90")}
        assert passes_configuration(_candidate(opportunity_score=Decimal("80")), config) is False

    def test_fails_when_above_a_max_threshold(self):
        config = {"max_risk_score": Decimal("10")}
        assert passes_configuration(_candidate(risk_score=Decimal("20")), config) is False

    def test_passes_when_at_or_below_max_threshold(self):
        config = {"max_risk_score": Decimal("20")}
        assert passes_configuration(_candidate(risk_score=Decimal("20")), config) is True

    def test_missing_data_for_a_configured_threshold_fails_closed(self):
        config = {"min_liquidity_usd": Decimal("1000")}
        assert passes_configuration(_candidate(liquidity_usd=None), config) is False

    def test_missing_data_for_an_unconfigured_threshold_does_not_matter(self):
        config = {"min_opportunity_score": Decimal("50")}
        assert passes_configuration(_candidate(liquidity_usd=None), config) is True


class TestSimulateConfiguration:
    def test_no_candidates_gives_empty_result(self):
        result = simulate_configuration({}, [])
        assert result.total_candidates == 0
        assert result.passing_count == 0
        assert result.pass_rate_pct == Decimal("0")

    def test_pass_rate_computed_correctly(self):
        candidates = [
            _candidate(opportunity_score=Decimal("90")),
            _candidate(opportunity_score=Decimal("40")),
            _candidate(opportunity_score=Decimal("95")),
            _candidate(opportunity_score=Decimal("30")),
        ]
        result = simulate_configuration({"min_opportunity_score": Decimal("50")}, candidates)
        assert result.total_candidates == 4
        assert result.passing_count == 2
        assert result.pass_rate_pct == Decimal("50.00")

    def test_avg_opportunity_score_only_over_passing_candidates(self):
        candidates = [
            _candidate(opportunity_score=Decimal("90")),
            _candidate(opportunity_score=Decimal("10")),
        ]
        result = simulate_configuration({"min_opportunity_score": Decimal("50")}, candidates)
        assert result.avg_opportunity_score_passing == Decimal("90.00")

    def test_no_passing_candidates_leaves_avg_score_none(self):
        candidates = [_candidate(opportunity_score=Decimal("10"))]
        result = simulate_configuration({"min_opportunity_score": Decimal("90")}, candidates)
        assert result.avg_opportunity_score_passing is None

    def test_estimated_alerts_per_day_uses_window(self):
        candidates = [_candidate() for _ in range(14)]
        result = simulate_configuration({}, candidates, window_days=Decimal("7"))
        assert result.estimated_alerts_per_day == Decimal("2.00")

    def test_no_window_leaves_estimate_none(self):
        candidates = [_candidate()]
        result = simulate_configuration({}, candidates, window_days=None)
        assert result.estimated_alerts_per_day is None

    def test_hit_rate_fields_are_always_none(self):
        """Honest scope limit: no outcome data exists yet (Batch 11)."""
        result = simulate_configuration({}, [_candidate()])
        assert result.estimated_2x_hit_rate is None
        assert result.estimated_3x_hit_rate is None
        assert result.estimated_false_positive_rate is None

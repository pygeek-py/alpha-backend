from decimal import Decimal

from apps.configuration.evaluation import evaluate_proposed_configuration
from apps.configuration.simulation import SimulationResult


def _sim(**overrides) -> SimulationResult:
    defaults = dict(
        total_candidates=100,
        passing_count=20,
        pass_rate_pct=Decimal("20.00"),
        avg_opportunity_score_passing=Decimal("75.00"),
        estimated_alerts_per_day=Decimal("2.86"),
    )
    defaults.update(overrides)
    return SimulationResult(**defaults)


class TestEvaluateProposedConfiguration:
    def test_no_changes_is_neutral(self):
        config = {"min_opportunity_score": Decimal("80")}
        result = evaluate_proposed_configuration(
            current=config, proposed=dict(config), recommended={},
            simulation_current=_sim(), simulation_proposed=_sim(),
        )
        assert result.changed_fields == []
        assert result.verdict == "neutral"

    def test_moving_toward_recommendation_scores_well(self):
        """PRD S44's second example: proposing Minimum Score 86 when AI
        recommends something near there should be Recommended."""
        current = {"min_opportunity_score": Decimal("82")}
        proposed = {"min_opportunity_score": Decimal("86")}
        recommended = {"min_opportunity_score": Decimal("90")}
        result = evaluate_proposed_configuration(
            current=current, proposed=proposed, recommended=recommended,
            simulation_current=_sim(passing_count=20),
            simulation_proposed=_sim(passing_count=15),
        )
        assert result.recommendation_score > Decimal("50")

    def test_moving_away_from_recommendation_scores_poorly(self):
        """PRD S44's first example: proposing a LOWER minimum score than
        current, when the AI recommends keeping it high, should score low."""
        current = {"min_opportunity_score": Decimal("82")}
        proposed = {"min_opportunity_score": Decimal("75")}
        recommended = {"min_opportunity_score": Decimal("90")}
        result = evaluate_proposed_configuration(
            current=current, proposed=proposed, recommended=recommended,
            simulation_current=_sim(passing_count=20),
            simulation_proposed=_sim(passing_count=60),
        )
        assert result.recommendation_score < Decimal("50")
        assert result.verdict in ("not_recommended", "strongly_discouraged")

    def test_volume_collapse_is_flagged(self):
        current = {"min_opportunity_score": Decimal("50")}
        proposed = {"min_opportunity_score": Decimal("99")}
        result = evaluate_proposed_configuration(
            current=current, proposed=proposed, recommended={},
            simulation_current=_sim(passing_count=20),
            simulation_proposed=_sim(passing_count=0),
        )
        assert any("almost no alerts" in e for e in result.expected_effects)

    def test_volume_surge_is_flagged(self):
        current = {"min_opportunity_score": Decimal("80")}
        proposed = {"min_opportunity_score": Decimal("40")}
        result = evaluate_proposed_configuration(
            current=current, proposed=proposed, recommended={},
            simulation_current=_sim(passing_count=10),
            simulation_proposed=_sim(passing_count=30),
        )
        assert any("lower average signal quality" in e for e in result.expected_effects)

    def test_missing_recommendation_data_defaults_to_neutral_alignment(self):
        current = {"min_opportunity_score": Decimal("80")}
        proposed = {"min_opportunity_score": Decimal("70")}
        result = evaluate_proposed_configuration(
            current=current, proposed=proposed, recommended={},  # no recommendation available
            simulation_current=_sim(passing_count=20), simulation_proposed=_sim(passing_count=20),
        )
        # No alignment signal and no volume change -- score should sit at the neutral midpoint.
        assert result.recommendation_score == Decimal("50.00")

    def test_recommendation_score_never_leaves_0_100(self):
        current = {"min_opportunity_score": Decimal("10")}
        proposed = {"min_opportunity_score": Decimal("99")}
        recommended = {"min_opportunity_score": Decimal("10")}
        result = evaluate_proposed_configuration(
            current=current, proposed=proposed, recommended=recommended,
            simulation_current=_sim(passing_count=50),
            simulation_proposed=_sim(passing_count=0),
        )
        assert Decimal("0") <= result.recommendation_score <= Decimal("100")

    def test_verdict_bands(self):
        from apps.configuration.evaluation import _verdict_for

        assert _verdict_for(Decimal("90")) == "strongly_recommended"
        assert _verdict_for(Decimal("70")) == "reasonable"
        assert _verdict_for(Decimal("50")) == "neutral"
        assert _verdict_for(Decimal("30")) == "not_recommended"
        assert _verdict_for(Decimal("10")) == "strongly_discouraged"

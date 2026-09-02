from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from apps.predictions.rules import compute_prediction, compute_score_5x, score_to_probability

CATEGORY_DEFAULTS = {
    "safety_score": Decimal("80"),
    "liquidity_score": Decimal("70"),
    "momentum_score": Decimal("60"),
    "holder_growth_score": Decimal("50"),
    "wallet_score": Decimal("40"),
    "buy_pressure_score": Decimal("30"),
    "price_structure_score": Decimal("20"),
    "narrative_score": Decimal("10"),
    "creator_score": Decimal("90"),
}


def _token_score(**overrides):
    defaults = {
        **CATEGORY_DEFAULTS,
        "opportunity_score": Decimal("65"),
        "risk_score": Decimal("25"),
        "score_2x": Decimal("70"),
        "score_3x": Decimal("55"),
        "explanation": {"positive": [], "negative": [], "missing": []},
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestScoreToProbability:
    def test_none_score_gives_zero(self):
        assert score_to_probability(None) == Decimal("0.0000")

    def test_100_score_gives_1(self):
        assert score_to_probability(Decimal("100")) == Decimal("1.0000")

    def test_0_score_gives_0(self):
        assert score_to_probability(Decimal("0")) == Decimal("0.0000")

    def test_midpoint(self):
        assert score_to_probability(Decimal("50")) == Decimal("0.5000")

    def test_out_of_range_high_is_clamped(self):
        assert score_to_probability(Decimal("150")) == Decimal("1.0000")

    def test_out_of_range_low_is_clamped(self):
        assert score_to_probability(Decimal("-10")) == Decimal("0.0000")


class TestComputeScore5x:
    def test_all_categories_present(self):
        result = compute_score_5x(_token_score())
        assert Decimal("0") <= result <= Decimal("100")

    def test_no_categories_present_is_none(self):
        token_score = _token_score(**{k: None for k in CATEGORY_DEFAULTS})
        assert compute_score_5x(token_score) is None

    def test_missing_categories_renormalize_over_the_rest(self):
        # momentum(8) and buy_pressure(3) are both below the input's own
        # category value (60, 30) relative to the overall mix -- dropping
        # them and renormalizing should measurably shift the result, not
        # silently default the missing weight to 0.
        full = compute_score_5x(_token_score())
        partial = compute_score_5x(_token_score(momentum_score=None, buy_pressure_score=None))
        assert Decimal("0") <= partial <= Decimal("100")
        assert partial != full

    def test_high_safety_and_wallet_dominate_the_weighting(self):
        strong = _token_score(safety_score=Decimal("100"), wallet_score=Decimal("100"))
        weak = _token_score(safety_score=Decimal("0"), wallet_score=Decimal("0"))
        assert compute_score_5x(strong) > compute_score_5x(weak)


class TestComputePrediction:
    def test_probabilities_derive_from_the_matching_scores(self):
        token_score = _token_score(score_2x=Decimal("80"), score_3x=Decimal("60"))
        result = compute_prediction(
            token_score=token_score, current_market_cap=None, historical_median_time_to_2x=None
        )
        assert result.probability_2x == Decimal("0.8000")
        assert result.probability_3x == Decimal("0.6000")

    def test_risk_probability_derives_from_risk_score(self):
        token_score = _token_score(risk_score=Decimal("30"))
        result = compute_prediction(
            token_score=token_score, current_market_cap=None, historical_median_time_to_2x=None
        )
        assert result.risk_probability == Decimal("0.3000")

    def test_no_historical_basis_leaves_expected_time_none(self):
        result = compute_prediction(
            token_score=_token_score(), current_market_cap=None, historical_median_time_to_2x=None
        )
        assert result.expected_time_to_target is None

    def test_historical_basis_is_used_directly(self):
        basis = timedelta(minutes=34)
        result = compute_prediction(
            token_score=_token_score(), current_market_cap=None, historical_median_time_to_2x=basis
        )
        assert result.expected_time_to_target == basis

    def test_feature_snapshot_includes_target_market_caps(self):
        result = compute_prediction(
            token_score=_token_score(),
            current_market_cap=Decimal("100000"),
            historical_median_time_to_2x=None,
        )
        assert result.feature_snapshot["target_market_cap_2x"] == "200000"
        assert result.feature_snapshot["target_market_cap_3x"] == "300000"
        assert result.feature_snapshot["target_market_cap_5x"] == "500000"

    def test_missing_market_cap_omits_target_market_caps(self):
        result = compute_prediction(
            token_score=_token_score(), current_market_cap=None, historical_median_time_to_2x=None
        )
        assert "target_market_cap_2x" not in result.feature_snapshot
        assert result.feature_snapshot["current_market_cap"] is None

    def test_feature_snapshot_carries_the_explanation_through(self):
        explanation = {"positive": ["Volume acceleration"], "negative": [], "missing": []}
        result = compute_prediction(
            token_score=_token_score(explanation=explanation),
            current_market_cap=None,
            historical_median_time_to_2x=None,
        )
        assert result.feature_snapshot["explanation"] == explanation

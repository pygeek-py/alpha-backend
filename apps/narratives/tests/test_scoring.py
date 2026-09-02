from decimal import Decimal

from apps.narratives.scoring import (
    blend_with_social_signal,
    compute_narrative_competition,
    compute_narrative_momentum,
    compute_narrative_strength,
)


class TestComputeNarrativeStrength:
    def test_no_activity_is_zero(self):
        score = compute_narrative_strength(active_token_count=0, total_market_cap=None, total_volume_5m=None)
        assert score == Decimal("0.00")

    def test_full_strength_when_all_components_maxed(self):
        score = compute_narrative_strength(
            active_token_count=20, total_market_cap=Decimal("5000000"), total_volume_5m=Decimal("100000")
        )
        assert score == Decimal("100.00")

    def test_exceeding_thresholds_does_not_exceed_100(self):
        score = compute_narrative_strength(
            active_token_count=500, total_market_cap=Decimal("50000000"), total_volume_5m=Decimal("1000000")
        )
        assert score == Decimal("100.00")

    def test_partial_activity_gives_partial_score(self):
        score = compute_narrative_strength(
            active_token_count=10, total_market_cap=Decimal("2500000"), total_volume_5m=Decimal("50000")
        )
        # 10/20*40=20, 50000/100000*30=15, 2500000/5000000*30=15 -> 50
        assert score == Decimal("50.00")

    def test_token_count_alone_without_market_data(self):
        score = compute_narrative_strength(active_token_count=20, total_market_cap=None, total_volume_5m=None)
        assert score == Decimal("40.00")


class TestComputeNarrativeMomentum:
    def test_no_previous_observation_returns_none(self):
        assert compute_narrative_momentum(Decimal("80"), None) is None

    def test_zero_previous_returns_none(self):
        assert compute_narrative_momentum(Decimal("80"), Decimal("0")) is None

    def test_no_change_is_neutral_50(self):
        assert compute_narrative_momentum(Decimal("60"), Decimal("60")) == Decimal("50.00")

    def test_growth_pushes_above_50(self):
        # +50% change -> 50 + 25 = 75
        result = compute_narrative_momentum(Decimal("90"), Decimal("60"))
        assert result == Decimal("75.00")

    def test_decline_pushes_below_50(self):
        result = compute_narrative_momentum(Decimal("30"), Decimal("60"))
        assert result == Decimal("25.00")

    def test_extreme_growth_caps_at_100(self):
        result = compute_narrative_momentum(Decimal("1000"), Decimal("10"))
        assert result == Decimal("100.00")

    def test_extreme_decline_floors_at_0(self):
        # -100% change (strength collapsed to zero) -> 50 - 50 = 0, the floor.
        result = compute_narrative_momentum(Decimal("0"), Decimal("1000"))
        assert result == Decimal("0.00")


class TestComputeNarrativeCompetition:
    def test_low_competition(self):
        result = compute_narrative_competition(3)
        assert result.label == "low"

    def test_moderate_competition(self):
        result = compute_narrative_competition(12)
        assert result.label == "moderate"

    def test_high_competition(self):
        result = compute_narrative_competition(50)
        assert result.label == "high"
        assert result.active_token_count == 50

    def test_boundary_at_5_is_low(self):
        assert compute_narrative_competition(5).label == "low"

    def test_boundary_at_6_is_moderate(self):
        assert compute_narrative_competition(6).label == "moderate"


class TestBlendWithSocialSignal:
    def test_no_signal_returns_onchain_unchanged(self):
        result = blend_with_social_signal(Decimal("70"), None)
        assert result == Decimal("70")

    def test_signal_with_no_previous_mentions_returns_onchain_unchanged(self):
        signal = _signal(mention_count_current=100, mention_count_previous=None)
        result = blend_with_social_signal(Decimal("70"), signal)
        assert result == Decimal("70")

    def test_growing_mentions_pulls_score_up(self):
        signal = _signal(mention_count_current=200, mention_count_previous=100)  # +100%
        result = blend_with_social_signal(Decimal("40"), signal)
        # social component = 50 + 100/2 = 100; blended = (40+100)/2 = 70
        assert result == Decimal("70.00")

    def test_declining_mentions_pulls_score_down(self):
        signal = _signal(mention_count_current=50, mention_count_previous=100)  # -50%
        result = blend_with_social_signal(Decimal("80"), signal)
        # social component = 50 - 25 = 25; blended = (80+25)/2 = 52.5
        assert result == Decimal("52.50")


def _signal(mention_count_current, mention_count_previous):
    from types import SimpleNamespace

    return SimpleNamespace(
        mention_count_current=mention_count_current, mention_count_previous=mention_count_previous
    )

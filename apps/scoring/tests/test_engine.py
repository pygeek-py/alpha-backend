"""Pure-logic tests for the scoring engine -- deliberately DB-free. Safety
checks and narrative links are duck-typed SimpleNamespace stand-ins (engine.py
only accesses specific attributes, never queries); market/liquidity/holder
features use the real Batch 5 dataclasses since those are already plain and
cheap to construct.
"""

from decimal import Decimal
from types import SimpleNamespace

from apps.holders.features import HolderFeatures
from apps.liquidity.features import LiquidityFeatures
from apps.market_data.features import MarketFeatures
from apps.scoring.engine import (
    OPPORTUNITY_WEIGHTS,
    SCORE_2X_WEIGHTS,
    SCORE_3X_WEIGHTS,
    CategoryScore,
    WalletActivitySummaryForToken,
    build_explanation,
    compute_risk_score,
    compute_token_score,
    score_buy_pressure,
    score_creator_history,
    score_holder_growth,
    score_liquidity,
    score_momentum,
    score_narrative,
    score_price_structure,
    score_safety,
    score_wallet_intelligence,
)


def _safety_check(**overrides):
    defaults = dict(
        score=Decimal("85"),
        risk_level="LOW",
        hard_rejection=False,
        hard_rejection_reasons=[],
        warnings=[],
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestScoreSafety:
    def test_none_is_missing(self):
        result = score_safety(None)
        assert result.score is None
        assert result.missing

    def test_high_score_is_positive(self):
        result = score_safety(_safety_check(score=Decimal("90")))
        assert result.score == Decimal("90")
        assert result.positive
        assert not result.negative

    def test_low_score_is_negative(self):
        result = score_safety(_safety_check(score=Decimal("40"), risk_level="HIGH"))
        assert result.negative

    def test_hard_rejection_is_always_negative(self):
        result = score_safety(
            _safety_check(score=Decimal("90"), hard_rejection=True, hard_rejection_reasons=["bad thing"])
        )
        assert result.negative
        assert "bad thing" in result.negative[0]

    def test_warnings_become_negatives(self):
        result = score_safety(_safety_check(warnings=["LP not locked"]))
        assert any("LP not locked" in n for n in result.negative)


class TestScoreLiquidity:
    def test_none_is_missing(self):
        result = score_liquidity(None)
        assert result.score is None

    def test_high_ratio_is_positive(self):
        result = score_liquidity(
            LiquidityFeatures(liquidity_mcap_ratio_pct=Decimal("15"))
        )
        assert result.score > Decimal("50")
        assert result.positive

    def test_low_ratio_is_negative(self):
        result = score_liquidity(
            LiquidityFeatures(liquidity_mcap_ratio_pct=Decimal("1"))
        )
        assert result.score < Decimal("50")
        assert result.negative

    def test_liquidity_drop_is_negative(self):
        result = score_liquidity(LiquidityFeatures(liquidity_change_pct=Decimal("-30")))
        assert result.negative

    def test_missing_ratio_is_disclosed(self):
        result = score_liquidity(LiquidityFeatures())
        assert result.score is not None  # partial data -- still scored
        assert result.missing


class TestScoreMomentum:
    def test_none_is_missing(self):
        assert score_momentum(None).score is None

    def test_strong_acceleration_is_positive(self):
        result = score_momentum(MarketFeatures(volume_5m_acceleration=Decimal("3")))
        assert result.positive

    def test_declining_volume_is_negative(self):
        result = score_momentum(MarketFeatures(volume_5m_acceleration=Decimal("0.2")))
        assert result.negative

    def test_pump_and_dump_risk_is_negative(self):
        result = score_momentum(MarketFeatures(pump_and_dump_risk=True))
        assert any("pump" in n.lower() for n in result.negative)

    def test_price_direction_up_is_positive(self):
        result = score_momentum(MarketFeatures(price_direction="up", price_change_pct=Decimal("20")))
        assert result.positive


class TestScoreHolderGrowth:
    def test_none_is_missing(self):
        assert score_holder_growth(None).score is None

    def test_strong_growth_is_positive(self):
        result = score_holder_growth(HolderFeatures(holder_growth_pct=Decimal("50")))
        assert result.positive

    def test_decline_is_negative(self):
        result = score_holder_growth(HolderFeatures(holder_growth_pct=Decimal("-10")))
        assert result.negative

    def test_accelerating_growth_adds_positive(self):
        result = score_holder_growth(
            HolderFeatures(holder_growth_pct=Decimal("10"), holder_growth_acceleration=Decimal("3"))
        )
        assert any("accelerat" in p.lower() for p in result.positive)

    def test_diluting_concentration_is_positive(self):
        result = score_holder_growth(HolderFeatures(concentration_change_pct=Decimal("-10")))
        assert any("dilut" in p.lower() for p in result.positive)


class TestScoreWalletIntelligence:
    def test_no_wallets_is_missing(self):
        assert score_wallet_intelligence(None).score is None
        assert score_wallet_intelligence(WalletActivitySummaryForToken()).score is None

    def test_smart_money_presence_is_positive(self):
        result = score_wallet_intelligence(
            WalletActivitySummaryForToken(
                smart_money_count=2, smart_money_avg_reputation=Decimal("90"), total_tracked_wallets=5
            )
        )
        assert result.positive
        assert result.score > Decimal("50")

    def test_no_smart_money_is_negative(self):
        result = score_wallet_intelligence(WalletActivitySummaryForToken(total_tracked_wallets=5))
        assert result.negative

    def test_insider_or_bundled_presence_is_negative(self):
        result = score_wallet_intelligence(
            WalletActivitySummaryForToken(insider_or_bundled_count=2, total_tracked_wallets=5)
        )
        assert result.negative
        assert any("insider" in n.lower() for n in result.negative)


class TestScoreBuyPressure:
    def test_none_is_missing(self):
        assert score_buy_pressure(None).score is None
        assert score_buy_pressure(MarketFeatures()).score is None

    def test_high_buy_pressure_is_positive(self):
        result = score_buy_pressure(MarketFeatures(buy_pressure_pct_5m=Decimal("80")))
        assert result.score == Decimal("80")
        assert result.positive

    def test_low_buy_pressure_is_negative(self):
        result = score_buy_pressure(MarketFeatures(buy_pressure_pct_5m=Decimal("20")))
        assert result.negative


class TestScorePriceStructure:
    def test_none_is_missing(self):
        assert score_price_structure(None).score is None

    def test_uptrend_is_positive(self):
        result = score_price_structure(MarketFeatures(price_structure="uptrend"))
        assert result.positive

    def test_downtrend_is_negative(self):
        result = score_price_structure(MarketFeatures(price_structure="downtrend"))
        assert result.negative

    def test_breakout_adds_positive(self):
        features = MarketFeatures(price_structure="consolidating", breakout_detected=True)
        result = score_price_structure(features)
        assert any("breakout" in p.lower() or "resistance" in p.lower() for p in result.positive)

    def test_large_drawdown_is_negative(self):
        result = score_price_structure(
            MarketFeatures(price_structure="consolidating", drawdown_from_ath_pct=Decimal("70"))
        )
        assert result.negative


class TestScoreNarrative:
    def test_no_links_is_missing(self):
        assert score_narrative([]).score is None

    def test_picks_highest_relevance_link(self):
        low = SimpleNamespace(
            relevance_score=Decimal("30"), strength_score=None, momentum_score=None,
            narrative=SimpleNamespace(name="Low"),
        )
        high = SimpleNamespace(
            relevance_score=Decimal("90"), strength_score=Decimal("80"), momentum_score=Decimal("70"),
            narrative=SimpleNamespace(name="High"),
        )
        result = score_narrative([low, high])
        assert "High" in result.positive[0]

    def test_missing_strength_and_momentum_disclosed(self):
        link = SimpleNamespace(
            relevance_score=Decimal("50"), strength_score=None, momentum_score=None,
            narrative=SimpleNamespace(name="X"),
        )
        result = score_narrative([link])
        assert len(result.missing) == 2


class TestScoreCreatorHistory:
    def test_none_is_missing(self):
        assert score_creator_history(None).score is None

    def test_zero_prior_is_favorable(self):
        result = score_creator_history(0)
        assert result.score == Decimal("70")
        assert result.positive

    def test_serial_deployer_is_low_and_negative(self):
        result = score_creator_history(10)
        assert result.score == Decimal("10")
        assert result.negative


class TestComputeRiskScore:
    def test_inverse_of_safety_score(self):
        categories = {"safety": CategoryScore(score=Decimal("80"))}
        assert compute_risk_score(categories, None) == Decimal("20.00")

    def test_missing_safety_defaults_to_neutral_50(self):
        categories = {"safety": CategoryScore(score=None)}
        assert compute_risk_score(categories, None) == Decimal("50.00")

    def test_pump_and_dump_adds_penalty(self):
        categories = {"safety": CategoryScore(score=Decimal("80"))}
        market_features = MarketFeatures(pump_and_dump_risk=True)
        assert compute_risk_score(categories, market_features) == Decimal("35.00")

    def test_never_exceeds_100(self):
        categories = {"safety": CategoryScore(score=Decimal("0"))}
        market_features = MarketFeatures(pump_and_dump_risk=True)
        assert compute_risk_score(categories, market_features) == Decimal("100.00")


class TestBuildExplanation:
    def test_aggregates_across_categories_with_labels(self):
        categories = {
            "safety": CategoryScore(score=Decimal("90"), positive=["good"]),
            "liquidity": CategoryScore(score=Decimal("20"), negative=["bad"]),
            "momentum": CategoryScore(score=None, missing=["no data"]),
        }
        explanation = build_explanation(categories)
        assert explanation["positive"] == ["[safety] good"]
        assert explanation["negative"] == ["[liquidity] bad"]
        assert explanation["missing"] == ["[momentum] no data"]


class TestWeightTablesSumTo100:
    def test_opportunity_weights(self):
        assert sum(OPPORTUNITY_WEIGHTS.values()) == 100

    def test_2x_weights(self):
        assert sum(SCORE_2X_WEIGHTS.values()) == 100

    def test_3x_weights(self):
        assert sum(SCORE_3X_WEIGHTS.values()) == 100


class TestComputeTokenScoreOrchestration:
    def test_fully_populated_token_scores_all_categories(self):
        result = compute_token_score(
            safety_check=_safety_check(score=Decimal("90")),
            liquidity_features=LiquidityFeatures(liquidity_mcap_ratio_pct=Decimal("15")),
            market_features=MarketFeatures(
                volume_5m_acceleration=Decimal("3"),
                price_direction="up",
                price_change_pct=Decimal("10"),
                buy_pressure_pct_5m=Decimal("70"),
                price_structure="uptrend",
            ),
            holder_features=HolderFeatures(holder_growth_pct=Decimal("30")),
            wallet_summary=WalletActivitySummaryForToken(
                smart_money_count=1, smart_money_avg_reputation=Decimal("80"), total_tracked_wallets=3
            ),
            narrative_links=[
                SimpleNamespace(
                    relevance_score=Decimal("70"), strength_score=Decimal("60"), momentum_score=Decimal("60"),
                    narrative=SimpleNamespace(name="AI"),
                )
            ],
            prior_creator_token_count=0,
        )
        assert all(cat.score is not None for cat in result.categories.values())
        assert result.opportunity_score > Decimal("50")
        assert Decimal("0") <= result.risk_score <= Decimal("100")
        assert Decimal("0") <= result.score_2x <= Decimal("100")
        assert Decimal("0") <= result.score_3x <= Decimal("100")

    def test_fully_empty_token_still_produces_a_result(self):
        """No data at all for any category -- must not crash, and every
        category should be disclosed as missing."""
        result = compute_token_score()
        assert all(cat.score is None for cat in result.categories.values())
        assert result.opportunity_score == Decimal("0")
        assert result.score_2x == Decimal("0")
        assert result.score_3x == Decimal("0")
        assert len(result.explanation["missing"]) == 9

    def test_missing_categories_are_excluded_via_renormalization(self):
        """Only safety data available -- opportunity score should equal the
        safety score itself (100% of available weight), not be diluted by
        treating the other 8 categories as zero."""
        result = compute_token_score(safety_check=_safety_check(score=Decimal("80")))
        assert result.opportunity_score == Decimal("80.00")

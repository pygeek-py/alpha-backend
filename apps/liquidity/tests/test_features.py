from decimal import Decimal

from apps.liquidity.features import extract_liquidity_features
from apps.liquidity.models import LiquiditySnapshot


def _snapshot(**overrides) -> LiquiditySnapshot:
    defaults = dict(liquidity_usd=Decimal("50000"))
    defaults.update(overrides)
    return LiquiditySnapshot(**defaults)


class TestLiquidityChange:
    def test_no_previous_leaves_change_none(self):
        result = extract_liquidity_features(_snapshot(), previous=None)
        assert result.liquidity_change_pct is None

    def test_growth_percentage_and_signal(self):
        result = extract_liquidity_features(
            _snapshot(liquidity_usd=Decimal("90000")), previous=_snapshot(liquidity_usd=Decimal("50000"))
        )
        assert result.liquidity_change_pct == Decimal("80.00")
        assert any("grew" in s for s in result.signals)

    def test_sharp_drop_is_flagged_as_a_possible_pull(self):
        result = extract_liquidity_features(
            _snapshot(liquidity_usd=Decimal("10000")), previous=_snapshot(liquidity_usd=Decimal("50000"))
        )
        assert result.liquidity_change_pct == Decimal("-80.00")
        assert any("possible pull" in s for s in result.signals)

    def test_small_change_produces_no_signal(self):
        result = extract_liquidity_features(
            _snapshot(liquidity_usd=Decimal("52000")), previous=_snapshot(liquidity_usd=Decimal("50000"))
        )
        assert result.signals == []


class TestLiquidityMcapRatio:
    def test_no_market_cap_leaves_ratio_none(self):
        result = extract_liquidity_features(_snapshot(), market_cap=None)
        assert result.liquidity_mcap_ratio_pct is None

    def test_ratio_computed_correctly(self):
        result = extract_liquidity_features(
            _snapshot(liquidity_usd=Decimal("50000")), market_cap=Decimal("500000")
        )
        assert result.liquidity_mcap_ratio_pct == Decimal("10.00")

    def test_low_ratio_produces_a_signal(self):
        result = extract_liquidity_features(
            _snapshot(liquidity_usd=Decimal("10000")), market_cap=Decimal("10000000")
        )
        assert result.liquidity_mcap_ratio_pct == Decimal("0.10")
        assert any("only" in s for s in result.signals)


class TestVolumeLiquidityRatio:
    def test_computed_when_both_available(self):
        result = extract_liquidity_features(
            _snapshot(liquidity_usd=Decimal("50000")), volume_5m=Decimal("25000")
        )
        assert result.volume_liquidity_ratio == Decimal("0.5000")

    def test_none_when_volume_missing(self):
        result = extract_liquidity_features(_snapshot(), volume_5m=None)
        assert result.volume_liquidity_ratio is None


class TestEstimatedPriceImpact:
    def test_thin_liquidity_has_higher_estimated_impact(self):
        thin = extract_liquidity_features(_snapshot(liquidity_usd=Decimal("1000")))
        deep = extract_liquidity_features(_snapshot(liquidity_usd=Decimal("1000000")))
        assert thin.estimated_price_impact_pct > deep.estimated_price_impact_pct

    def test_zero_liquidity_leaves_impact_none(self):
        result = extract_liquidity_features(_snapshot(liquidity_usd=Decimal("0")))
        assert result.estimated_price_impact_pct is None

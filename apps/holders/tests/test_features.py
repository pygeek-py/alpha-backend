from decimal import Decimal

from apps.holders.features import extract_holder_features
from apps.holders.models import HolderSnapshot


def _snapshot(**overrides) -> HolderSnapshot:
    defaults = dict(holder_count=500, top_holder_pct=Decimal("10"))
    defaults.update(overrides)
    return HolderSnapshot(**defaults)


class TestHolderGrowth:
    def test_no_previous_leaves_growth_none(self):
        result = extract_holder_features(_snapshot(), previous=None)
        assert result.holder_growth_count is None
        assert result.holder_growth_pct is None

    def test_prd_example_400_to_1000_holders(self):
        result = extract_holder_features(
            _snapshot(holder_count=1000), previous=_snapshot(holder_count=400)
        )
        assert result.holder_growth_count == 600
        assert result.holder_growth_pct == Decimal("150.00")
        assert any("400 -> 1000" in s for s in result.signals)

    def test_small_growth_produces_no_signal(self):
        result = extract_holder_features(
            _snapshot(holder_count=410), previous=_snapshot(holder_count=400)
        )
        assert result.signals == []

    def test_holder_count_can_decrease(self):
        result = extract_holder_features(
            _snapshot(holder_count=380), previous=_snapshot(holder_count=400)
        )
        assert result.holder_growth_count == -20
        assert result.holder_growth_pct == Decimal("-5.00")


class TestConcentrationChange:
    def test_dilution_is_flagged(self):
        result = extract_holder_features(
            _snapshot(top_holder_pct=Decimal("10")), previous=_snapshot(top_holder_pct=Decimal("20"))
        )
        assert result.concentration_change_pct == Decimal("-10.00")
        assert any("diluting" in s for s in result.signals)

    def test_small_change_is_not_flagged(self):
        result = extract_holder_features(
            _snapshot(top_holder_pct=Decimal("19")), previous=_snapshot(top_holder_pct=Decimal("20"))
        )
        assert result.signals == []

    def test_missing_percentages_leaves_change_none(self):
        result = extract_holder_features(
            _snapshot(top_holder_pct=None), previous=_snapshot(top_holder_pct=Decimal("20"))
        )
        assert result.concentration_change_pct is None


class TestGrowthAcceleration:
    def test_needs_all_three_snapshots(self):
        result = extract_holder_features(_snapshot(holder_count=1000), previous=_snapshot(holder_count=400))
        assert result.holder_growth_acceleration is None

    def test_accelerating_growth_is_flagged(self):
        # earlier -> previous: 100 -> 200 (+100%); previous -> current: 200 -> 600 (+200%)
        # acceleration = 200/100 = 2x
        result = extract_holder_features(
            _snapshot(holder_count=600),
            previous=_snapshot(holder_count=200),
            earlier=_snapshot(holder_count=100),
        )
        assert result.holder_growth_acceleration == Decimal("2.0000")
        assert any("accelerating" in s for s in result.signals)

    def test_decelerating_growth_is_not_flagged(self):
        # earlier -> previous: 100 -> 500 (+400%); previous -> current: 500 -> 600 (+20%)
        result = extract_holder_features(
            _snapshot(holder_count=600),
            previous=_snapshot(holder_count=500),
            earlier=_snapshot(holder_count=100),
        )
        assert result.holder_growth_acceleration < Decimal("1")
        assert not any("accelerating" in s for s in result.signals)

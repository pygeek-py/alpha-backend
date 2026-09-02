"""Pure-logic tests -- deliberately DB-free (plain unsaved TokenSnapshot
instances), since extract_market_features() takes every input explicitly."""

from decimal import Decimal

from apps.market_data.features import extract_market_features
from apps.market_data.models import TokenSnapshot


def _snapshot(**overrides) -> TokenSnapshot:
    defaults = dict(
        price=Decimal("0.001"),
        volume_5m=Decimal("4000"),
        volume_15m=Decimal("12000"),
        volume_1h=Decimal("40000"),
        buy_volume_5m=Decimal("2000"),
        sell_volume_5m=Decimal("2000"),
    )
    defaults.update(overrides)
    return TokenSnapshot(**defaults)


class TestVolumeAcceleration:
    def test_no_previous_snapshot_leaves_acceleration_none(self):
        result = extract_market_features(_snapshot(), previous=None)
        assert result.volume_5m_acceleration is None

    def test_prd_example_4k_to_12k_is_3x(self):
        # PRD S13's own worked example: current 10m volume $12K, previous
        # $4K -> acceleration = 3x. Using the 5m field here as the same shape.
        result = extract_market_features(
            _snapshot(volume_5m=Decimal("12000")), previous=_snapshot(volume_5m=Decimal("4000"))
        )
        assert result.volume_5m_acceleration == Decimal("3.0000")

    def test_large_acceleration_produces_a_signal(self):
        result = extract_market_features(
            _snapshot(volume_5m=Decimal("12000")), previous=_snapshot(volume_5m=Decimal("4000"))
        )
        assert any("accelerated" in s for s in result.signals)

    def test_small_acceleration_produces_no_signal(self):
        result = extract_market_features(
            _snapshot(volume_5m=Decimal("4500")), previous=_snapshot(volume_5m=Decimal("4000"))
        )
        assert result.signals == []

    def test_zero_previous_volume_does_not_divide_by_zero(self):
        result = extract_market_features(_snapshot(), previous=_snapshot(volume_5m=Decimal("0")))
        assert result.volume_5m_acceleration is None


class TestBuySellPressure:
    def test_buy_sell_ratio(self):
        result = extract_market_features(
            _snapshot(buy_volume_5m=Decimal("3000"), sell_volume_5m=Decimal("1000"))
        )
        assert result.buy_sell_ratio_5m == Decimal("3.0000")

    def test_zero_sell_volume_does_not_divide_by_zero(self):
        result = extract_market_features(
            _snapshot(buy_volume_5m=Decimal("1000"), sell_volume_5m=Decimal("0"))
        )
        assert result.buy_sell_ratio_5m is None

    def test_buy_pressure_percentage(self):
        result = extract_market_features(
            _snapshot(volume_5m=Decimal("4000"), buy_volume_5m=Decimal("3000"))
        )
        assert result.buy_pressure_pct_5m == Decimal("75.00")


class TestPriceMomentum:
    def test_price_direction_up(self):
        result = extract_market_features(
            _snapshot(price=Decimal("0.002")), previous=_snapshot(price=Decimal("0.001"))
        )
        assert result.price_direction == "up"
        assert result.price_change_pct == Decimal("100.00")

    def test_price_direction_down(self):
        result = extract_market_features(
            _snapshot(price=Decimal("0.001")), previous=_snapshot(price=Decimal("0.002"))
        )
        assert result.price_direction == "down"

    def test_price_direction_flat(self):
        result = extract_market_features(
            _snapshot(price=Decimal("0.001")), previous=_snapshot(price=Decimal("0.001"))
        )
        assert result.price_direction == "flat"

    def test_no_previous_snapshot_direction_unknown(self):
        result = extract_market_features(_snapshot())
        assert result.price_direction == "unknown"


class TestPumpAndDumpRisk:
    def test_large_pump_with_sell_dominant_volume_is_flagged(self):
        result = extract_market_features(
            _snapshot(
                price=Decimal("0.0013"),  # +30% vs previous
                volume_5m=Decimal("4000"),
                buy_volume_5m=Decimal("1000"),  # 25% buy pressure -- sell-dominant
            ),
            previous=_snapshot(price=Decimal("0.001")),
        )
        assert result.pump_and_dump_risk is True
        assert any("pump and dump" in s for s in result.signals)

    def test_large_pump_with_buy_dominant_volume_is_not_flagged(self):
        result = extract_market_features(
            _snapshot(
                price=Decimal("0.0013"),
                volume_5m=Decimal("4000"),
                buy_volume_5m=Decimal("3500"),  # 87.5% buy pressure
            ),
            previous=_snapshot(price=Decimal("0.001")),
        )
        assert result.pump_and_dump_risk is False

    def test_small_price_increase_is_not_flagged_regardless_of_sell_pressure(self):
        result = extract_market_features(
            _snapshot(
                price=Decimal("0.00105"),  # +5% only
                volume_5m=Decimal("4000"),
                buy_volume_5m=Decimal("500"),
            ),
            previous=_snapshot(price=Decimal("0.001")),
        )
        assert result.pump_and_dump_risk is False


class TestDrawdownFromAth:
    def test_no_history_leaves_drawdown_none(self):
        result = extract_market_features(_snapshot(), history=[])
        assert result.drawdown_from_ath_pct is None

    def test_current_price_is_the_ath(self):
        result = extract_market_features(
            _snapshot(price=Decimal("0.002")), history=[_snapshot(price=Decimal("0.001"))]
        )
        assert result.drawdown_from_ath_pct == Decimal("0.00")

    def test_drawdown_from_a_higher_historical_price(self):
        result = extract_market_features(
            _snapshot(price=Decimal("0.0005")), history=[_snapshot(price=Decimal("0.001"))]
        )
        assert result.drawdown_from_ath_pct == Decimal("50.00")


class TestBreakout:
    def test_insufficient_history_no_breakout(self):
        result = extract_market_features(
            _snapshot(price=Decimal("0.002")), history=[_snapshot(price=Decimal("0.001"))]
        )
        assert result.breakout_detected is False

    def test_price_above_resistance_with_volume_confirmation_is_a_breakout(self):
        history = [
            _snapshot(price=Decimal("0.001"), volume_5m=Decimal("1000")),
            _snapshot(price=Decimal("0.0012"), volume_5m=Decimal("1000")),
            _snapshot(price=Decimal("0.0011"), volume_5m=Decimal("1000")),
        ]
        result = extract_market_features(
            _snapshot(price=Decimal("0.002"), volume_5m=Decimal("5000")), history=history
        )
        assert result.breakout_detected is True
        assert any("resistance" in s for s in result.signals)

    def test_price_above_resistance_without_volume_confirmation_is_not_a_breakout(self):
        history = [
            _snapshot(price=Decimal("0.001"), volume_5m=Decimal("5000")),
            _snapshot(price=Decimal("0.0012"), volume_5m=Decimal("5000")),
            _snapshot(price=Decimal("0.0011"), volume_5m=Decimal("5000")),
        ]
        result = extract_market_features(
            _snapshot(price=Decimal("0.002"), volume_5m=Decimal("100")), history=history
        )
        assert result.breakout_detected is False

    def test_price_below_resistance_is_not_a_breakout(self):
        history = [
            _snapshot(price=Decimal("0.005")),
            _snapshot(price=Decimal("0.004")),
            _snapshot(price=Decimal("0.006")),
        ]
        result = extract_market_features(_snapshot(price=Decimal("0.002")), history=history)
        assert result.breakout_detected is False


class TestPriceStructure:
    def test_insufficient_history_is_insufficient_data(self):
        history = [_snapshot(price=Decimal("0.001")), _snapshot(price=Decimal("0.002"))]
        result = extract_market_features(_snapshot(), history=history)
        assert result.price_structure == "insufficient_data"

    def test_higher_highs_and_higher_lows_is_uptrend(self):
        history = [
            _snapshot(price=Decimal("0.001")),
            _snapshot(price=Decimal("0.0012")),  # first half: min=0.001, max=0.0012
            _snapshot(price=Decimal("0.0015")),
            _snapshot(price=Decimal("0.0018")),  # second half: min=0.0015, max=0.0018
        ]
        result = extract_market_features(_snapshot(), history=history)
        assert result.price_structure == "uptrend"

    def test_lower_highs_and_lower_lows_is_downtrend(self):
        history = [
            _snapshot(price=Decimal("0.0018")),
            _snapshot(price=Decimal("0.0015")),  # first half: min=0.0015, max=0.0018
            _snapshot(price=Decimal("0.0012")),
            _snapshot(price=Decimal("0.001")),  # second half: min=0.001, max=0.0012
        ]
        result = extract_market_features(_snapshot(), history=history)
        assert result.price_structure == "downtrend"

    def test_mixed_signals_is_consolidating(self):
        history = [
            _snapshot(price=Decimal("0.001")),
            _snapshot(price=Decimal("0.002")),  # first half: min=0.001, max=0.002
            _snapshot(price=Decimal("0.0015")),
            _snapshot(price=Decimal("0.0018")),  # second half: lower high (0.0018<0.002), higher low
        ]
        result = extract_market_features(_snapshot(), history=history)
        assert result.price_structure == "consolidating"

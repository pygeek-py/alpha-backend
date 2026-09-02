"""Market/momentum feature extraction (PRD S13-14). Pure functions -- every
input is an explicit snapshot or list of snapshots, never queried here (see
apps/market_data/services.py for that). The core principle throughout (PRD
S13): compare current values against previous observations, never score a
raw value alone -- a $12K 5m-volume snapshot means something different
following a $4K one than following a $40K one.

`history` (where accepted) must be ordered chronologically oldest-to-newest
and must NOT include `current` -- the service layer is responsible for that
ordering; these functions don't re-sort.
"""

from dataclasses import dataclass, field
from decimal import Decimal

# A 2x volume jump or more is treated as acceleration worth flagging (PRD S13's
# own example: $4K -> $12K = "Acceleration = 3x").
ACCELERATION_SIGNAL_THRESHOLD = Decimal("2")
PUMP_PRICE_CHANGE_THRESHOLD = Decimal("20")
PUMP_SELL_DOMINANT_BUY_PRESSURE_CEILING = Decimal("40")
MIN_HISTORY_FOR_BREAKOUT = 3
MIN_HISTORY_FOR_STRUCTURE = 4


def _ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return (numerator / denominator).quantize(Decimal("0.0001"))


def _pct_change(current: Decimal | None, previous: Decimal | None) -> Decimal | None:
    if current is None or previous is None or previous == 0:
        return None
    return ((current - previous) / previous * 100).quantize(Decimal("0.01"))


def _pct_of(part: Decimal | None, whole: Decimal | None) -> Decimal | None:
    if part is None or whole is None or whole == 0:
        return None
    return (part / whole * 100).quantize(Decimal("0.01"))


@dataclass
class MarketFeatures:
    volume_5m_acceleration: Decimal | None = None
    volume_15m_acceleration: Decimal | None = None
    volume_1h_acceleration: Decimal | None = None

    buy_sell_ratio_5m: Decimal | None = None
    buy_pressure_pct_5m: Decimal | None = None

    price_change_pct: Decimal | None = None
    price_direction: str = "unknown"  # "up" | "down" | "flat" | "unknown"
    pump_and_dump_risk: bool = False

    breakout_detected: bool = False
    # "uptrend" | "downtrend" | "consolidating" | "insufficient_data"
    price_structure: str = "insufficient_data"
    drawdown_from_ath_pct: Decimal | None = None

    signals: list[str] = field(default_factory=list)


def extract_market_features(current, previous=None, history=()) -> MarketFeatures:
    features = MarketFeatures()
    history = list(history)

    if previous is not None:
        features.volume_5m_acceleration = _ratio(current.volume_5m, previous.volume_5m)
        features.volume_15m_acceleration = _ratio(current.volume_15m, previous.volume_15m)
        features.volume_1h_acceleration = _ratio(current.volume_1h, previous.volume_1h)

        if (
            features.volume_5m_acceleration is not None
            and features.volume_5m_acceleration >= ACCELERATION_SIGNAL_THRESHOLD
        ):
            features.signals.append(f"5m volume accelerated {features.volume_5m_acceleration}x")

        features.price_change_pct = _pct_change(current.price, previous.price)
        if features.price_change_pct is None:
            features.price_direction = "unknown"
        elif features.price_change_pct > 0:
            features.price_direction = "up"
        elif features.price_change_pct < 0:
            features.price_direction = "down"
        else:
            features.price_direction = "flat"

    features.buy_sell_ratio_5m = _ratio(current.buy_volume_5m, current.sell_volume_5m)
    features.buy_pressure_pct_5m = _pct_of(current.buy_volume_5m, current.volume_5m)

    # PRD S14: "avoid assuming every large price increase is bullish -- a
    # rapid pump followed by extreme selling should increase risk."
    if (
        features.price_change_pct is not None
        and features.price_change_pct > PUMP_PRICE_CHANGE_THRESHOLD
        and features.buy_pressure_pct_5m is not None
        and features.buy_pressure_pct_5m < PUMP_SELL_DOMINANT_BUY_PRESSURE_CEILING
    ):
        features.pump_and_dump_risk = True
        features.signals.append(
            f"Price up {features.price_change_pct}% but sell-dominant volume "
            f"({100 - features.buy_pressure_pct_5m}% sell) -- possible pump and dump"
        )

    prices_in_history = [s.price for s in history if s.price is not None]
    if prices_in_history:
        ath = max(prices_in_history + [current.price])
        if ath > 0:
            features.drawdown_from_ath_pct = ((ath - current.price) / ath * 100).quantize(Decimal("0.01"))

    if len(history) >= MIN_HISTORY_FOR_BREAKOUT and prices_in_history:
        resistance = max(prices_in_history)
        volumes_in_history = [s.volume_5m for s in history if s.volume_5m is not None]
        avg_volume = (sum(volumes_in_history) / len(volumes_in_history)) if volumes_in_history else None
        volume_confirms = (
            current.volume_5m is not None and avg_volume is not None and current.volume_5m > avg_volume
        )
        if current.price > resistance and (avg_volume is None or volume_confirms):
            features.breakout_detected = True
            features.signals.append(f"Price broke above recent resistance (${resistance})")

    if len(history) >= MIN_HISTORY_FOR_STRUCTURE:
        midpoint = len(history) // 2
        first_half, second_half = history[:midpoint], history[midpoint:]
        first_prices = [s.price for s in first_half if s.price is not None]
        second_prices = [s.price for s in second_half if s.price is not None]
        if first_prices and second_prices:
            higher_highs = max(second_prices) > max(first_prices)
            higher_lows = min(second_prices) > min(first_prices)
            lower_highs = max(second_prices) < max(first_prices)
            lower_lows = min(second_prices) < min(first_prices)
            if higher_highs and higher_lows:
                features.price_structure = "uptrend"
            elif lower_highs and lower_lows:
                features.price_structure = "downtrend"
            else:
                features.price_structure = "consolidating"

    return features

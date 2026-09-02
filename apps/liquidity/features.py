"""Liquidity feature extraction (PRD S12). Pure functions -- inputs are
explicit snapshots/values, never queried here (see services.py). PRD S12's
own example: $500K market cap with $150K liquidity is a very different risk
profile than $500K market cap with $15K liquidity -- the ratio matters more
than either raw number.
"""

from dataclasses import dataclass, field
from decimal import Decimal

LOW_LIQUIDITY_MCAP_RATIO_PCT = Decimal("3")

# Rough small-trade price-impact approximation for a constant-product AMM:
# impact ~= trade_size / (2 * pool_liquidity_usd). This is an approximation,
# not exact -- LiquiditySnapshot stores aggregate pool value, not separate
# base/quote reserves, so an exact constant-product calculation isn't
# possible from this data. Good enough to flag "thin liquidity, expect real
# slippage," not precise enough to size an actual trade against.
REFERENCE_TRADE_SIZE_USD = Decimal("500")


def _pct_change(current: Decimal | None, previous: Decimal | None) -> Decimal | None:
    if current is None or previous is None or previous == 0:
        return None
    return ((current - previous) / previous * 100).quantize(Decimal("0.01"))


@dataclass
class LiquidityFeatures:
    liquidity_change_pct: Decimal | None = None
    liquidity_mcap_ratio_pct: Decimal | None = None
    volume_liquidity_ratio: Decimal | None = None
    estimated_price_impact_pct: Decimal | None = None
    signals: list[str] = field(default_factory=list)


def extract_liquidity_features(
    current, previous=None, *, market_cap: Decimal | None = None, volume_5m: Decimal | None = None
) -> LiquidityFeatures:
    features = LiquidityFeatures()

    if previous is not None:
        features.liquidity_change_pct = _pct_change(current.liquidity_usd, previous.liquidity_usd)
        if features.liquidity_change_pct is not None and features.liquidity_change_pct <= Decimal("-25"):
            features.signals.append(f"Liquidity dropped {features.liquidity_change_pct}% -- possible pull")
        elif features.liquidity_change_pct is not None and features.liquidity_change_pct >= Decimal("50"):
            features.signals.append(f"Liquidity grew {features.liquidity_change_pct}%")

    if market_cap and market_cap > 0:
        features.liquidity_mcap_ratio_pct = (current.liquidity_usd / market_cap * 100).quantize(
            Decimal("0.01")
        )
        if features.liquidity_mcap_ratio_pct < LOW_LIQUIDITY_MCAP_RATIO_PCT:
            features.signals.append(
                f"Liquidity is only {features.liquidity_mcap_ratio_pct}% of market cap"
            )

    if volume_5m is not None and current.liquidity_usd:
        features.volume_liquidity_ratio = (volume_5m / current.liquidity_usd).quantize(Decimal("0.0001"))

    if current.liquidity_usd and current.liquidity_usd > 0:
        features.estimated_price_impact_pct = (
            REFERENCE_TRADE_SIZE_USD / (2 * current.liquidity_usd) * 100
        ).quantize(Decimal("0.01"))

    return features

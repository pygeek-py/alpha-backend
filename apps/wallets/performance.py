"""Wallet performance computation (PRD S17). Pure functions -- every input
is pre-fetched data (a buy transaction plus the token's subsequent price
snapshots), never queried here (see services.py).

Important honesty note: without reliably matched sell transactions for every
buy, "performance" here means the *opportunity* a buy presented (the best
price the token reached afterward), not confirmed realized profit/loss --
we don't actually know if the wallet sold at that peak, sold earlier, or
never sold at all. `avg_multiple`/`win_rate`/etc. are labeled and documented
as opportunity-based throughout rather than silently implying certainty
about what the wallet actually pocketed.
"""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

WIN_THRESHOLD_MULTIPLE = Decimal("1")  # price went up at all after the buy
MIN_TRADES_FOR_FULL_CONFIDENCE = 10


@dataclass
class BuyEvaluation:
    multiple: Decimal  # best price reached after the buy, divided by buy price
    is_win: bool
    matched_sell_holding_time: timedelta | None = None


def evaluate_buy(
    buy_price: Decimal, subsequent_prices: list, matched_sell_holding_time=None
) -> BuyEvaluation | None:
    """`subsequent_prices` is every known price observed strictly after the
    buy (from TokenSnapshot history), oldest-to-newest order doesn't matter
    here -- only the max is used. Returns None if there's no buy price or no
    subsequent data to evaluate against yet.
    """
    if not buy_price or buy_price <= 0 or not subsequent_prices:
        return None

    max_price_after = max(subsequent_prices)
    multiple = (max_price_after / buy_price).quantize(Decimal("0.0001"))
    return BuyEvaluation(
        multiple=multiple,
        is_win=multiple >= WIN_THRESHOLD_MULTIPLE,
        matched_sell_holding_time=matched_sell_holding_time,
    )


@dataclass
class PerformanceMetrics:
    trade_count: int
    evaluable_buy_count: int
    win_rate: Decimal | None = None
    avg_multiple: Decimal | None = None
    median_multiple: Decimal | None = None
    max_multiple: Decimal | None = None
    successful_2x_count: int = 0
    successful_3x_count: int = 0
    successful_5x_count: int = 0
    avg_holding_time: timedelta | None = None


def aggregate_performance(evaluations: list[BuyEvaluation], *, trade_count: int) -> PerformanceMetrics:
    if not evaluations:
        return PerformanceMetrics(trade_count=trade_count, evaluable_buy_count=0)

    multiples = sorted(e.multiple for e in evaluations)
    n = len(multiples)
    win_count = sum(1 for e in evaluations if e.is_win)

    mid = n // 2
    median = multiples[mid] if n % 2 == 1 else (multiples[mid - 1] + multiples[mid]) / 2

    holding_times = [e.matched_sell_holding_time for e in evaluations if e.matched_sell_holding_time]
    avg_holding_time = (sum(holding_times, timedelta()) / len(holding_times)) if holding_times else None

    return PerformanceMetrics(
        trade_count=trade_count,
        evaluable_buy_count=n,
        win_rate=(Decimal(win_count) / n * 100).quantize(Decimal("0.01")),
        avg_multiple=(sum(multiples) / n).quantize(Decimal("0.0001")),
        median_multiple=median.quantize(Decimal("0.0001")),
        max_multiple=max(multiples),
        successful_2x_count=sum(1 for m in multiples if m >= 2),
        successful_3x_count=sum(1 for m in multiples if m >= 3),
        successful_5x_count=sum(1 for m in multiples if m >= 5),
        avg_holding_time=avg_holding_time,
    )


def compute_reputation_score(metrics: PerformanceMetrics) -> Decimal | None:
    """0-100, confidence-weighted so a wallet with only 1-2 evaluable trades
    doesn't swing straight to 0 or 100 -- its score is pulled toward a
    neutral 50 in proportion to how little evidence exists. This score is
    purely performance-based; it says nothing about *why* the wallet
    performed well, which is exactly what classification.py separately
    determines (PRD S18: profitable alone must never imply smart money).
    """
    if metrics.evaluable_buy_count == 0 or metrics.win_rate is None or metrics.avg_multiple is None:
        return None

    multiple_component = min(max((metrics.avg_multiple - 1) * 25, Decimal("0")), Decimal("100"))
    raw_score = (metrics.win_rate * Decimal("0.5")) + (multiple_component * Decimal("0.5"))

    confidence = min(Decimal(metrics.evaluable_buy_count) / MIN_TRADES_FOR_FULL_CONFIDENCE, Decimal("1"))
    neutral = Decimal("50")
    return (neutral + (raw_score - neutral) * confidence).quantize(Decimal("0.01"))

from datetime import timedelta
from decimal import Decimal

from apps.wallets.performance import (
    BuyEvaluation,
    aggregate_performance,
    compute_reputation_score,
    evaluate_buy,
)


class TestEvaluateBuy:
    def test_no_buy_price_returns_none(self):
        assert evaluate_buy(None, [Decimal("1")]) is None
        assert evaluate_buy(Decimal("0"), [Decimal("1")]) is None

    def test_no_subsequent_prices_returns_none(self):
        assert evaluate_buy(Decimal("1"), []) is None

    def test_multiple_is_best_subsequent_price_over_buy_price(self):
        result = evaluate_buy(Decimal("1"), [Decimal("1.5"), Decimal("3"), Decimal("2")])
        assert result.multiple == Decimal("3.0000")

    def test_is_win_when_multiple_at_least_one(self):
        result = evaluate_buy(Decimal("1"), [Decimal("1.0")])
        assert result.is_win is True

    def test_is_not_win_when_price_only_dropped(self):
        result = evaluate_buy(Decimal("1"), [Decimal("0.5"), Decimal("0.3")])
        assert result.is_win is False

    def test_holding_time_is_passed_through(self):
        result = evaluate_buy(Decimal("1"), [Decimal("2")], matched_sell_holding_time=timedelta(minutes=5))
        assert result.matched_sell_holding_time == timedelta(minutes=5)


class TestAggregatePerformance:
    def test_no_evaluations_gives_empty_metrics(self):
        metrics = aggregate_performance([], trade_count=5)
        assert metrics.trade_count == 5
        assert metrics.evaluable_buy_count == 0
        assert metrics.win_rate is None

    def test_win_rate_computed_correctly(self):
        evaluations = [
            BuyEvaluation(multiple=Decimal("2"), is_win=True),
            BuyEvaluation(multiple=Decimal("0.5"), is_win=False),
            BuyEvaluation(multiple=Decimal("3"), is_win=True),
            BuyEvaluation(multiple=Decimal("0.8"), is_win=False),
        ]
        metrics = aggregate_performance(evaluations, trade_count=10)
        assert metrics.win_rate == Decimal("50.00")
        assert metrics.evaluable_buy_count == 4

    def test_avg_and_max_multiple(self):
        evaluations = [
            BuyEvaluation(multiple=Decimal("2"), is_win=True),
            BuyEvaluation(multiple=Decimal("4"), is_win=True),
        ]
        metrics = aggregate_performance(evaluations, trade_count=2)
        assert metrics.avg_multiple == Decimal("3.0000")
        assert metrics.max_multiple == Decimal("4")

    def test_median_multiple_odd_count(self):
        evaluations = [
            BuyEvaluation(multiple=Decimal("1"), is_win=True),
            BuyEvaluation(multiple=Decimal("5"), is_win=True),
            BuyEvaluation(multiple=Decimal("2"), is_win=True),
        ]
        metrics = aggregate_performance(evaluations, trade_count=3)
        assert metrics.median_multiple == Decimal("2.0000")

    def test_median_multiple_even_count(self):
        evaluations = [
            BuyEvaluation(multiple=Decimal("1"), is_win=True),
            BuyEvaluation(multiple=Decimal("3"), is_win=True),
        ]
        metrics = aggregate_performance(evaluations, trade_count=2)
        assert metrics.median_multiple == Decimal("2.0000")

    def test_successful_multiple_thresholds(self):
        evaluations = [
            BuyEvaluation(multiple=Decimal("1.5"), is_win=True),
            BuyEvaluation(multiple=Decimal("2.5"), is_win=True),
            BuyEvaluation(multiple=Decimal("3.5"), is_win=True),
            BuyEvaluation(multiple=Decimal("6"), is_win=True),
        ]
        metrics = aggregate_performance(evaluations, trade_count=4)
        assert metrics.successful_2x_count == 3
        assert metrics.successful_3x_count == 2
        assert metrics.successful_5x_count == 1

    def test_avg_holding_time_only_over_matched_sells(self):
        evaluations = [
            BuyEvaluation(
                multiple=Decimal("2"), is_win=True, matched_sell_holding_time=timedelta(minutes=10)
            ),
            BuyEvaluation(
                multiple=Decimal("3"), is_win=True, matched_sell_holding_time=timedelta(minutes=20)
            ),
            BuyEvaluation(multiple=Decimal("1"), is_win=True),  # no matched sell -- excluded
        ]
        metrics = aggregate_performance(evaluations, trade_count=3)
        assert metrics.avg_holding_time == timedelta(minutes=15)

    def test_no_matched_sells_leaves_holding_time_none(self):
        evaluations = [BuyEvaluation(multiple=Decimal("2"), is_win=True)]
        metrics = aggregate_performance(evaluations, trade_count=1)
        assert metrics.avg_holding_time is None


class TestComputeReputationScore:
    def test_no_evaluable_trades_returns_none(self):
        metrics = aggregate_performance([], trade_count=5)
        assert compute_reputation_score(metrics) is None

    def test_strong_performance_with_full_confidence_scores_high(self):
        evaluations = [BuyEvaluation(multiple=Decimal("5"), is_win=True) for _ in range(15)]
        metrics = aggregate_performance(evaluations, trade_count=15)
        score = compute_reputation_score(metrics)
        assert score > Decimal("90")

    def test_weak_performance_with_full_confidence_scores_low(self):
        evaluations = [BuyEvaluation(multiple=Decimal("0.5"), is_win=False) for _ in range(15)]
        metrics = aggregate_performance(evaluations, trade_count=15)
        score = compute_reputation_score(metrics)
        assert score < Decimal("10")

    def test_low_confidence_pulls_score_toward_neutral(self):
        # Same strong performance, but only 1 trade -- should NOT be near 100.
        evaluations = [BuyEvaluation(multiple=Decimal("5"), is_win=True)]
        metrics = aggregate_performance(evaluations, trade_count=1)
        score = compute_reputation_score(metrics)
        assert Decimal("50") < score < Decimal("90")

    def test_single_trade_stays_close_to_neutral(self):
        evaluations = [BuyEvaluation(multiple=Decimal("5"), is_win=True)]
        metrics = aggregate_performance(evaluations, trade_count=1)
        score = compute_reputation_score(metrics)
        # confidence = 1/10 -> score should be close to 50, not swing wildly
        assert score < Decimal("60")

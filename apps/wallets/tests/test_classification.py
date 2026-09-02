from decimal import Decimal

from apps.wallets.classification import EarlyEntry, WalletActivitySummary, classify_wallet
from apps.wallets.models import Wallet


def _summary(**overrides) -> WalletActivitySummary:
    defaults = dict(trade_count=0, buy_count=0, sell_count=0)
    defaults.update(overrides)
    return WalletActivitySummary(**defaults)


class TestCreatorClassification:
    def test_creator_flag_wins_regardless_of_other_signals(self):
        summary = _summary(
            is_creator_of_any_token=True,
            evaluable_buy_count=20,
            win_rate=Decimal("90"),
            avg_multiple=Decimal("5"),
        )
        result = classify_wallet(summary)
        assert result.classification == Wallet.Classification.CREATOR
        assert result.confidence == Decimal("100")


class TestInsiderClassification:
    def test_early_entries_concentrated_on_one_creator_is_insider(self):
        summary = _summary(
            early_entries=[
                EarlyEntry("TokenA", "CreatorX", 5),
                EarlyEntry("TokenB", "CreatorX", 10),
                EarlyEntry("TokenC", "CreatorX", 8),
            ]
        )
        result = classify_wallet(summary)
        assert result.classification == Wallet.Classification.INSIDER
        assert "CreatorX"[:8] in result.reasons[0] or "CreatorX" in result.reasons[0]

    def test_early_entries_spread_across_different_creators_is_not_insider(self):
        summary = _summary(
            early_entries=[
                EarlyEntry("TokenA", "CreatorX", 5),
                EarlyEntry("TokenB", "CreatorY", 10),
                EarlyEntry("TokenC", "CreatorZ", 8),
            ]
        )
        result = classify_wallet(summary)
        assert result.classification != Wallet.Classification.INSIDER

    def test_this_is_the_prds_own_warning_example(self):
        """PRD S18: "A wallet that repeatedly buys before the creator's
        tokens pump may not represent independent smart money." Even with
        excellent performance numbers, concentrated early entry on one
        creator must classify as INSIDER, not SMART_MONEY."""
        summary = _summary(
            early_entries=[
                EarlyEntry("TokenA", "SameCreator", 3),
                EarlyEntry("TokenB", "SameCreator", 4),
                EarlyEntry("TokenC", "SameCreator", 6),
            ],
            evaluable_buy_count=10,
            win_rate=Decimal("90"),
            avg_multiple=Decimal("8"),
        )
        result = classify_wallet(summary)
        assert result.classification == Wallet.Classification.INSIDER


class TestBundledClassification:
    def test_clustered_wallet_is_bundled(self):
        summary = _summary(is_clustered=True)
        result = classify_wallet(summary)
        assert result.classification == Wallet.Classification.BUNDLED

    def test_clustering_checked_before_bot_and_smart_money(self):
        summary = _summary(
            is_clustered=True,
            trade_count=50,
            avg_holding_time_seconds=10,
            evaluable_buy_count=20,
            win_rate=Decimal("90"),
            avg_multiple=Decimal("5"),
        )
        result = classify_wallet(summary)
        assert result.classification == Wallet.Classification.BUNDLED


class TestBotClassification:
    def test_high_frequency_short_holding_unbalanced_is_bot(self):
        summary = _summary(
            trade_count=40, buy_count=38, sell_count=2, avg_holding_time_seconds=5
        )
        result = classify_wallet(summary)
        assert result.classification == Wallet.Classification.BOT

    def test_low_frequency_short_holding_is_not_bot(self):
        summary = _summary(trade_count=5, buy_count=3, sell_count=2, avg_holding_time_seconds=5)
        result = classify_wallet(summary)
        assert result.classification != Wallet.Classification.BOT

    def test_long_holding_time_is_not_bot(self):
        summary = _summary(trade_count=40, buy_count=38, sell_count=2, avg_holding_time_seconds=3600)
        result = classify_wallet(summary)
        assert result.classification != Wallet.Classification.BOT


class TestMarketMakerClassification:
    def test_high_frequency_balanced_short_holding_is_market_maker(self):
        summary = _summary(
            trade_count=60, buy_count=30, sell_count=30, avg_holding_time_seconds=8
        )
        result = classify_wallet(summary)
        assert result.classification == Wallet.Classification.MARKET_MAKER

    def test_unbalanced_high_frequency_is_bot_not_market_maker(self):
        summary = _summary(
            trade_count=60, buy_count=55, sell_count=5, avg_holding_time_seconds=8
        )
        result = classify_wallet(summary)
        assert result.classification == Wallet.Classification.BOT


class TestSniperClassification:
    def test_multiple_fast_entries_across_unrelated_creators_is_sniper(self):
        summary = _summary(
            early_entries=[
                EarlyEntry("TokenA", "CreatorX", 5),
                EarlyEntry("TokenB", "CreatorY", 10),
                EarlyEntry("TokenC", "CreatorZ", 15),
            ]
        )
        result = classify_wallet(summary)
        assert result.classification == Wallet.Classification.SNIPER

    def test_only_two_fast_entries_is_not_enough_for_sniper(self):
        summary = _summary(
            early_entries=[
                EarlyEntry("TokenA", "CreatorX", 5),
                EarlyEntry("TokenB", "CreatorY", 10),
            ]
        )
        result = classify_wallet(summary)
        assert result.classification != Wallet.Classification.SNIPER

    def test_entries_outside_the_sniper_window_do_not_count(self):
        summary = _summary(
            early_entries=[
                EarlyEntry("TokenA", "CreatorX", 500),
                EarlyEntry("TokenB", "CreatorY", 600),
                EarlyEntry("TokenC", "CreatorZ", 700),
            ]
        )
        result = classify_wallet(summary)
        assert result.classification != Wallet.Classification.SNIPER


class TestSmartMoneyClassification:
    def test_strong_performance_with_no_red_flags_is_smart_money(self):
        summary = _summary(
            trade_count=10,
            evaluable_buy_count=10,
            win_rate=Decimal("70"),
            avg_multiple=Decimal("2.5"),
        )
        result = classify_wallet(summary)
        assert result.classification == Wallet.Classification.SMART_MONEY

    def test_profitable_but_too_few_trades_is_not_smart_money(self):
        """Core PRD S18 requirement: profitability alone is not enough."""
        summary = _summary(
            trade_count=2,
            evaluable_buy_count=2,
            win_rate=Decimal("100"),
            avg_multiple=Decimal("10"),
        )
        result = classify_wallet(summary)
        assert result.classification != Wallet.Classification.SMART_MONEY

    def test_low_win_rate_is_not_smart_money_even_with_good_multiple(self):
        summary = _summary(
            trade_count=10,
            evaluable_buy_count=10,
            win_rate=Decimal("30"),
            avg_multiple=Decimal("5"),
        )
        result = classify_wallet(summary)
        assert result.classification != Wallet.Classification.SMART_MONEY


class TestNormalAndUnknown:
    def test_enough_trades_but_no_pattern_is_normal(self):
        summary = _summary(
            trade_count=5,
            buy_count=3,
            sell_count=2,
            evaluable_buy_count=3,
            win_rate=Decimal("40"),
            avg_multiple=Decimal("1.1"),
        )
        result = classify_wallet(summary)
        assert result.classification == Wallet.Classification.NORMAL

    def test_almost_no_history_is_unknown(self):
        summary = _summary(trade_count=1, buy_count=1, sell_count=0)
        result = classify_wallet(summary)
        assert result.classification == Wallet.Classification.UNKNOWN
        assert result.confidence == Decimal("0")


class TestExplainability:
    def test_every_result_has_at_least_one_reason(self):
        for summary in [
            _summary(is_creator_of_any_token=True),
            _summary(trade_count=1),
            _summary(
                trade_count=10, evaluable_buy_count=10, win_rate=Decimal("70"), avg_multiple=Decimal("2.5")
            ),
        ]:
            result = classify_wallet(summary)
            assert len(result.reasons) >= 1

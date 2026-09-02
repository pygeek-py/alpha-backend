from decimal import Decimal

from providers.mock import MockMarketDataProvider, MockSolanaProvider, MockWalletDataProvider


class TestMockSolanaProvider:
    def test_discover_tokens_returns_requested_count(self):
        tokens = MockSolanaProvider().discover_tokens(limit=10)
        assert len(tokens) == 10

    def test_discovered_tokens_are_labeled_mock(self):
        tokens = MockSolanaProvider().discover_tokens(limit=1)
        assert tokens[0].is_mock is True
        assert tokens[0].source == "mock"

    def test_discover_tokens_addresses_are_unique_within_a_call(self):
        tokens = MockSolanaProvider().discover_tokens(limit=25)
        addresses = {t.address for t in tokens}
        assert len(addresses) == 25

    def test_holder_distribution_percentages_stay_in_bounds(self):
        dist = MockSolanaProvider().get_holder_distribution("SomeAddress111")
        assert dist.holder_count >= 1
        assert Decimal("0") <= dist.top_holder_pct <= Decimal("100")
        assert dist.top5_pct >= dist.top_holder_pct
        assert dist.top10_pct >= dist.top5_pct

    def test_holder_distribution_is_stable_within_the_same_time_bucket(self):
        provider = MockSolanaProvider()
        first = provider.get_holder_distribution("StableAddress111")
        second = provider.get_holder_distribution("StableAddress111")
        assert first.holder_count == second.holder_count
        assert first.top_holder_pct == second.top_holder_pct


class TestMockMarketDataProvider:
    def test_market_snapshot_price_is_positive(self):
        snapshot = MockMarketDataProvider().get_market_snapshot("SomeAddress222")
        assert snapshot.price > 0
        assert snapshot.market_cap > 0

    def test_buy_and_sell_volume_sum_to_total_5m_volume(self):
        snapshot = MockMarketDataProvider().get_market_snapshot("SomeAddress333")
        assert snapshot.buy_volume_5m + snapshot.sell_volume_5m == snapshot.volume_5m

    def test_different_tokens_get_different_base_prices(self):
        provider = MockMarketDataProvider()
        a = provider.get_market_snapshot("AddressA")
        b = provider.get_market_snapshot("AddressB")
        assert a.price != b.price

    def test_liquidity_snapshot_is_positive_and_labeled(self):
        snapshot = MockMarketDataProvider().get_liquidity_snapshot("SomeAddress444")
        assert snapshot.liquidity_usd > 0
        assert snapshot.is_mock is True


class TestMockWalletDataProvider:
    def test_returns_transactions_with_valid_sides(self):
        transactions = MockWalletDataProvider().get_recent_transactions("SomeAddress555", limit=5)
        assert len(transactions) == 5
        assert all(t.side in ("buy", "sell") for t in transactions)

    def test_transaction_signatures_are_unique(self):
        transactions = MockWalletDataProvider().get_recent_transactions("SomeAddress666", limit=15)
        signatures = {t.tx_signature for t in transactions}
        assert len(signatures) == len(transactions)

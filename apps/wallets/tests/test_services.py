from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.market_data.models import TokenSnapshot
from apps.tokens.factories import TokenFactory
from apps.wallets.factories import WalletFactory
from apps.wallets.models import Wallet, WalletTransaction
from apps.wallets.services import (
    calculate_wallet_performance,
    classify_and_score_wallet,
    collect_wallet_transactions,
    run_wallet_clustering,
)


@pytest.mark.django_db
class TestCollectWalletTransactions:
    def test_creates_transactions_and_wallets(self):
        token = TokenFactory()
        transactions = collect_wallet_transactions(token, limit=5)
        assert len(transactions) == 5
        assert WalletTransaction.objects.filter(token=token).count() == 5
        # Not necessarily 5 distinct wallets: the mock provider draws from a
        # recurring pool (PRD-realistic -- a wallet trading the same token
        # more than once in a batch is normal, not a bug). The real
        # invariant is "one Wallet row per distinct address referenced."
        distinct_addresses = (
            WalletTransaction.objects.filter(token=token).values_list("wallet_id", flat=True).distinct()
        )
        assert Wallet.objects.count() == distinct_addresses.count()

    def test_rerunning_does_not_duplicate(self):
        token = TokenFactory()
        collect_wallet_transactions(token, limit=5)
        count_after_first = WalletTransaction.objects.count()
        collect_wallet_transactions(token, limit=5)
        assert WalletTransaction.objects.count() == count_after_first


def _buy(wallet, token, occurred_at, price=Decimal("1"), sig=None):
    return WalletTransaction.objects.create(
        wallet=wallet,
        token=token,
        tx_signature=sig or f"buy-{wallet.address}-{token.address}-{occurred_at.isoformat()}",
        side=WalletTransaction.Side.BUY,
        amount_tokens=Decimal("1000"),
        price=price,
        occurred_at=occurred_at,
    )


@pytest.mark.django_db
class TestCalculateWalletPerformance:
    def test_computes_and_persists_metrics(self):
        token = TokenFactory(launched_at=timezone.now() - timedelta(hours=1))
        wallet = WalletFactory()
        buy_time = timezone.now() - timedelta(minutes=30)
        _buy(wallet, token, buy_time)
        TokenSnapshot.objects.create(
            token=token, timestamp=buy_time + timedelta(minutes=10), price=Decimal("3")
        )

        performance = calculate_wallet_performance(wallet)

        assert performance.trade_count == 1
        assert performance.avg_multiple == Decimal("3.0000")
        assert performance.reputation_score is not None
        assert performance.last_calculated_at is not None

    def test_no_transactions_gives_empty_performance(self):
        wallet = WalletFactory()
        performance = calculate_wallet_performance(wallet)
        assert performance.trade_count == 0
        assert performance.reputation_score is None

    def test_recalculating_updates_the_same_row_not_a_duplicate(self):
        wallet = WalletFactory()
        calculate_wallet_performance(wallet)
        calculate_wallet_performance(wallet)
        from apps.wallets.models import WalletPerformance

        assert WalletPerformance.objects.filter(wallet=wallet).count() == 1


@pytest.mark.django_db
class TestClassifyAndScoreWallet:
    def test_creator_wallet_classified_as_creator(self):
        wallet = WalletFactory()
        TokenFactory(creator_address=wallet.address)

        wallet, _ = classify_and_score_wallet(wallet)

        wallet.refresh_from_db()
        assert wallet.classification == Wallet.Classification.CREATOR
        assert len(wallet.classification_reasons) >= 1

    def test_strong_independent_performance_classified_smart_money(self):
        wallet = WalletFactory()
        now = timezone.now()
        for i in range(10):
            token = TokenFactory(launched_at=now - timedelta(hours=2), creator_address=f"Creator{i}")
            buy_time = now - timedelta(hours=1)  # well outside the sniper window
            _buy(wallet, token, buy_time)
            TokenSnapshot.objects.create(
                token=token, timestamp=buy_time + timedelta(minutes=30), price=Decimal("3")
            )

        wallet, performance = classify_and_score_wallet(wallet)

        wallet.refresh_from_db()
        assert wallet.classification == Wallet.Classification.SMART_MONEY
        assert performance.win_rate == Decimal("100.00")

    def test_wallet_with_no_history_is_unknown(self):
        wallet = WalletFactory()
        wallet, _ = classify_and_score_wallet(wallet)
        wallet.refresh_from_db()
        assert wallet.classification == Wallet.Classification.UNKNOWN


@pytest.mark.django_db
class TestRunWalletClustering:
    def test_creates_cluster_for_tightly_coordinated_wallets(self):
        w1, w2 = WalletFactory(), WalletFactory()
        now = timezone.now()
        for i in range(3):
            token = TokenFactory()
            WalletTransaction.objects.create(
                wallet=w1,
                token=token,
                tx_signature=f"w1-{i}",
                side=WalletTransaction.Side.BUY,
                amount_tokens=Decimal("100"),
                occurred_at=now + timedelta(seconds=i * 100),
            )
            WalletTransaction.objects.create(
                wallet=w2,
                token=token,
                tx_signature=f"w2-{i}",
                side=WalletTransaction.Side.BUY,
                amount_tokens=Decimal("100"),
                occurred_at=now + timedelta(seconds=i * 100, milliseconds=500),
            )

        clusters = run_wallet_clustering()

        assert len(clusters) == 1
        w1.refresh_from_db()
        w2.refresh_from_db()
        assert w1.cluster_id == clusters[0].id
        assert w2.cluster_id == clusters[0].id

    def test_unrelated_wallets_produce_no_clusters(self):
        WalletFactory()
        WalletFactory()
        assert run_wallet_clustering() == []

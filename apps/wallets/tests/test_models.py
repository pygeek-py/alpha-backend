import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.tokens.factories import TokenFactory
from apps.wallets.factories import WalletFactory
from apps.wallets.models import Wallet, WalletPerformance, WalletTransaction


@pytest.mark.django_db
class TestWallet:
    def test_default_classification_is_unknown(self):
        wallet = WalletFactory()
        assert wallet.classification == Wallet.Classification.UNKNOWN

    def test_address_unique(self):
        WalletFactory(address="W1")
        with pytest.raises(IntegrityError):
            WalletFactory(address="W1")


@pytest.mark.django_db
class TestWalletTransaction:
    def test_create_and_relate(self):
        wallet = WalletFactory()
        token = TokenFactory()
        tx = WalletTransaction.objects.create(
            wallet=wallet,
            token=token,
            tx_signature="sig1",
            side=WalletTransaction.Side.BUY,
            amount_tokens="1000",
            occurred_at=timezone.now(),
        )
        assert wallet.transactions.get() == tx
        assert token.wallet_transactions.get() == tx

    def test_tx_signature_unique(self):
        wallet = WalletFactory()
        token = TokenFactory()
        WalletTransaction.objects.create(
            wallet=wallet,
            token=token,
            tx_signature="dup",
            side=WalletTransaction.Side.BUY,
            amount_tokens="1",
            occurred_at=timezone.now(),
        )
        with pytest.raises(IntegrityError):
            WalletTransaction.objects.create(
                wallet=wallet,
                token=token,
                tx_signature="dup",
                side=WalletTransaction.Side.SELL,
                amount_tokens="1",
                occurred_at=timezone.now(),
            )


@pytest.mark.django_db
class TestWalletPerformance:
    def test_one_to_one_with_wallet(self):
        wallet = WalletFactory()
        perf = WalletPerformance.objects.create(wallet=wallet, reputation_score="89.00")
        assert wallet.performance == perf
        assert perf.trade_count == 0

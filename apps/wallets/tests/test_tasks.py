from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.tokens.factories import TokenFactory
from apps.wallets.factories import WalletFactory
from apps.wallets.models import Wallet, WalletTransaction
from apps.wallets.tasks import (
    calculate_wallet_reputation,
    calculate_wallet_reputation_for_active_wallets,
    run_wallet_clustering_task,
)


@pytest.mark.django_db
def test_calculate_wallet_reputation_task_classifies_a_wallet():
    wallet = WalletFactory()
    TokenFactory(creator_address=wallet.address)

    result = calculate_wallet_reputation.delay(wallet.id)
    payload = result.get()

    assert payload["classification"] == Wallet.Classification.CREATOR
    wallet.refresh_from_db()
    assert wallet.classification == Wallet.Classification.CREATOR


@pytest.mark.django_db
def test_fan_out_only_queues_wallets_with_transactions():
    wallet_with_tx = WalletFactory()
    WalletFactory()  # no transactions -- should NOT be queued
    token = TokenFactory()
    WalletTransaction.objects.create(
        wallet=wallet_with_tx,
        token=token,
        tx_signature="sig1",
        side=WalletTransaction.Side.BUY,
        amount_tokens=Decimal("100"),
        occurred_at=timezone.now(),
    )

    result = calculate_wallet_reputation_for_active_wallets.delay()

    assert result.get()["queued"] == 1


@pytest.mark.django_db
def test_run_wallet_clustering_task_reports_cluster_count():
    w1, w2 = WalletFactory(), WalletFactory()
    now = timezone.now()
    for i in range(3):
        token = TokenFactory()
        WalletTransaction.objects.create(
            wallet=w1,
            token=token,
            tx_signature=f"c1-{i}",
            side=WalletTransaction.Side.BUY,
            amount_tokens=Decimal("100"),
            occurred_at=now + timedelta(seconds=i * 100),
        )
        WalletTransaction.objects.create(
            wallet=w2,
            token=token,
            tx_signature=f"c2-{i}",
            side=WalletTransaction.Side.BUY,
            amount_tokens=Decimal("100"),
            occurred_at=now + timedelta(seconds=i * 100, milliseconds=200),
        )

    result = run_wallet_clustering_task.delay()

    assert result.get()["clusters_found"] == 1

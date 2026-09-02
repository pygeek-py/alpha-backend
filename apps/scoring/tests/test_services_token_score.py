"""Service-layer (DB-backed) tests for compute_and_persist_token_score --
kept in a separate file from the existing test_services.py (safety-focused)
for readability given how much setup each scenario needs."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.holders.models import HolderSnapshot
from apps.liquidity.models import LiquiditySnapshot
from apps.market_data.models import TokenSnapshot
from apps.narratives.factories import NarrativeFactory
from apps.narratives.models import TokenNarrative
from apps.scoring.models import TokenScore
from apps.scoring.services import compute_and_persist_token_score
from apps.tokens.factories import TokenFactory
from apps.wallets.factories import WalletFactory
from apps.wallets.models import Wallet, WalletPerformance, WalletTransaction


@pytest.mark.django_db
class TestComputeAndPersistTokenScore:
    def test_token_with_no_data_still_produces_a_score(self):
        token = TokenFactory(mint_authority_revoked=None, freeze_authority_revoked=None)
        score = compute_and_persist_token_score(token)

        assert isinstance(score, TokenScore)
        assert score.token == token
        # safety always computes something (mint/freeze/etc checks run even
        # with no snapshots), so opportunity_score reflects at least that.
        assert score.explanation["missing"]

    def test_well_supported_token_scores_highly(self):
        token = TokenFactory(mint_authority_revoked=True, freeze_authority_revoked=True)
        now = timezone.now()

        LiquiditySnapshot.objects.create(
            token=token, timestamp=now, liquidity_usd=Decimal("100000"), lp_locked=True
        )
        TokenSnapshot.objects.create(
            token=token, timestamp=now, price=Decimal("0.001"), market_cap=Decimal("500000"),
            volume_5m=Decimal("20000"), buy_volume_5m=Decimal("15000"), sell_volume_5m=Decimal("5000"),
        )
        HolderSnapshot.objects.create(
            token=token, timestamp=now, holder_count=500, top_holder_pct=Decimal("5")
        )
        narrative = NarrativeFactory(keywords=["zyxquartz"])
        TokenNarrative.objects.create(
            token=token, narrative=narrative, relevance_score=Decimal("80"),
            strength_score=Decimal("70"), momentum_score=Decimal("70"), detected_at=now,
        )

        wallet = WalletFactory(classification=Wallet.Classification.SMART_MONEY)
        WalletPerformance.objects.create(wallet=wallet, reputation_score=Decimal("90"))
        WalletTransaction.objects.create(
            wallet=wallet, token=token, tx_signature="sig1", side=WalletTransaction.Side.BUY,
            amount_tokens=Decimal("1000"), occurred_at=now,
        )

        score = compute_and_persist_token_score(token)

        assert score.opportunity_score > Decimal("60")
        assert score.wallet_score is not None
        assert score.narrative_score is not None

    def test_poorly_supported_token_scores_low_and_flags_hard_rejection(self):
        token = TokenFactory(mint_authority_revoked=False, freeze_authority_revoked=False)
        score = compute_and_persist_token_score(token)

        assert score.opportunity_score < Decimal("50")
        assert any("Hard safety rejection" in n for n in score.explanation["negative"])

    def test_persists_score_2x_and_3x(self):
        token = TokenFactory()
        score = compute_and_persist_token_score(token)
        assert score.score_2x is not None
        assert score.score_3x is not None

    def test_uses_the_most_recent_snapshots(self):
        token = TokenFactory()
        now = timezone.now()
        TokenSnapshot.objects.create(
            token=token, timestamp=now, price=Decimal("0.001"), volume_5m=Decimal("1000")
        )
        TokenSnapshot.objects.create(
            token=token, timestamp=now + timedelta(minutes=5), price=Decimal("0.002"),
            volume_5m=Decimal("3000"),
        )

        score = compute_and_persist_token_score(token)

        assert any("accelerated" in p for p in score.explanation["positive"])

    def test_creates_a_new_row_each_call_not_updating_in_place(self):
        token = TokenFactory()
        compute_and_persist_token_score(token)
        compute_and_persist_token_score(token)
        assert TokenScore.objects.filter(token=token).count() == 2

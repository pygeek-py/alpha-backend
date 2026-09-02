from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.holders.models import HolderSnapshot
from apps.liquidity.models import LiquiditySnapshot
from apps.market_data.models import TokenSnapshot
from apps.scoring.models import TokenSafetyCheck
from apps.scoring.services import run_safety_analysis
from apps.tokens.factories import TokenFactory


@pytest.mark.django_db
class TestRunSafetyAnalysis:
    def test_persists_a_safety_check_using_latest_snapshots(self):
        token = TokenFactory(mint_authority_revoked=True, freeze_authority_revoked=True)

        # Two holder snapshots, explicitly ordered -- the analysis must use
        # the *latest* one (timestamps a second apart, not two back-to-back
        # timezone.now() calls, which can tie and make "latest" ambiguous).
        now = timezone.now()
        HolderSnapshot.objects.create(
            token=token, timestamp=now, holder_count=100, top_holder_pct=Decimal("80")
        )
        HolderSnapshot.objects.create(
            token=token, timestamp=now + timedelta(seconds=1), holder_count=200, top_holder_pct=Decimal("5")
        )
        LiquiditySnapshot.objects.create(
            token=token, timestamp=timezone.now(), liquidity_usd=Decimal("50000"), lp_locked=True
        )
        TokenSnapshot.objects.create(
            token=token, timestamp=timezone.now(), price=Decimal("0.01"), market_cap=Decimal("500000")
        )

        result = run_safety_analysis(token)

        assert isinstance(result, TokenSafetyCheck)
        assert result.token == token
        assert TokenSafetyCheck.objects.filter(pk=result.pk).exists()
        # The most recently created HolderSnapshot (top_holder_pct=5, safe)
        # should win, not the first one (top_holder_pct=80, would hard-reject).
        assert result.hard_rejection is False

    def test_token_with_no_snapshots_yet_still_produces_a_result(self):
        token = TokenFactory(mint_authority_revoked=None, freeze_authority_revoked=None)
        result = run_safety_analysis(token)
        assert result.score == 100  # nothing failed -- everything is just unknown
        assert result.hard_rejection is False

    def test_counts_prior_tokens_from_the_same_creator(self):
        TokenFactory.create_batch(4, creator_address="RepeatCreator111")
        newest = TokenFactory(creator_address="RepeatCreator111")

        result = run_safety_analysis(newest)

        creator_check = next(c for c in result.checks if c["name"] == "creator_history")
        assert "4 other tracked token" in creator_check["detail"]

    def test_hard_rejected_token_is_flagged_and_reasons_recorded(self):
        token = TokenFactory(mint_authority_revoked=False)
        result = run_safety_analysis(token)
        assert result.hard_rejection is True
        assert "Mint authority not revoked" in result.hard_rejection_reasons
        assert result.risk_level == TokenSafetyCheck.RiskLevel.EXTREME

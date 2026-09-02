from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.alerts.models import Alert, AlertEvent, AlertState
from apps.holders.models import HolderSnapshot
from apps.liquidity.models import LiquiditySnapshot
from apps.market_data.models import TokenSnapshot
from apps.narratives.factories import NarrativeFactory
from apps.narratives.models import TokenNarrative
from apps.outcomes.models import TokenOutcome
from apps.scoring.models import TokenScore
from apps.tokens.factories import TokenFactory
from apps.tokens.services import get_token_detail, get_token_history
from apps.wallets.factories import WalletFactory
from apps.wallets.models import Wallet, WalletPerformance, WalletTransaction


@pytest.mark.django_db
class TestGetTokenDetail:
    def test_overview_reflects_latest_snapshots(self):
        token = TokenFactory(symbol="PEPE")
        now = timezone.now()
        TokenSnapshot.objects.create(
            token=token, timestamp=now, price=Decimal("0.01"),
            market_cap=Decimal("50000"), volume_5m=Decimal("2000"),
        )
        LiquiditySnapshot.objects.create(token=token, timestamp=now, liquidity_usd=Decimal("15000"))
        HolderSnapshot.objects.create(token=token, timestamp=now, holder_count=250)

        detail = get_token_detail(token.id)

        assert detail["overview"]["symbol"] == "PEPE"
        assert detail["overview"]["market_cap"] == Decimal("50000")
        assert detail["overview"]["liquidity_usd"] == Decimal("15000")
        assert detail["overview"]["holder_count"] == 250
        assert detail["overview"]["state"] == "discovered"

    def test_score_is_none_without_a_tokenscore(self):
        token = TokenFactory()
        detail = get_token_detail(token.id)
        assert detail["score"] is None

    def test_score_breakdown_includes_all_categories(self):
        token = TokenFactory()
        TokenScore.objects.create(
            token=token, timestamp=timezone.now(), opportunity_score=Decimal("75"),
            risk_score=Decimal("15"), score_2x=Decimal("75"), score_3x=Decimal("60"),
            safety_score=Decimal("90"), momentum_score=Decimal("60"),
        )

        detail = get_token_detail(token.id)

        assert detail["score"]["opportunity_score"] == Decimal("75")
        assert detail["score"]["categories"]["safety_score"] == Decimal("90.00")
        assert detail["score"]["categories"]["momentum_score"] == Decimal("60.00")

    def test_no_narratives_gives_empty_list(self):
        token = TokenFactory()
        assert get_token_detail(token.id)["narratives"] == []

    def test_narrative_breakdown(self):
        token = TokenFactory()
        narrative = NarrativeFactory(name="Viral AI Meme", category="ai")
        TokenNarrative.objects.create(
            token=token, narrative=narrative, relevance_score=Decimal("85"),
            strength_score=Decimal("91"), momentum_score=Decimal("94"),
            detected_at=timezone.now(),
        )

        narratives = get_token_detail(token.id)["narratives"]

        assert len(narratives) == 1
        assert narratives[0]["name"] == "Viral AI Meme"
        assert narratives[0]["strength_score"] == Decimal("91.00")

    def test_no_outcome_yet_is_none(self):
        token = TokenFactory()
        assert get_token_detail(token.id)["outcome"] is None

    def test_outcome_from_latest_alert(self):
        token = TokenFactory()
        alert = Alert.objects.create(token=token, state=AlertState.CONFIRMED, score=Decimal("80"))
        TokenOutcome.objects.create(
            token=token, alert=alert, reference_timestamp=timezone.now(), initial_price="1",
            reached_2x=True, reached_3x=False, max_multiple=Decimal("2.4000"),
            time_to_2x=timedelta(minutes=34),
        )

        outcome = get_token_detail(token.id)["outcome"]

        assert outcome["reached_2x"] is True
        assert outcome["reached_3x"] is False
        assert outcome["max_multiple"] == Decimal("2.4000")
        assert outcome["time_to_2x"] == timedelta(minutes=34)

    def test_no_wallet_activity_gives_empty_list(self):
        token = TokenFactory()
        assert get_token_detail(token.id)["wallet_activity"] == []

    def test_wallet_activity_includes_reputation_and_classification(self):
        token = TokenFactory()
        wallet = WalletFactory(classification=Wallet.Classification.SMART_MONEY, label="Whale #1")
        WalletPerformance.objects.create(wallet=wallet, reputation_score=Decimal("89"))
        WalletTransaction.objects.create(
            wallet=wallet, token=token, tx_signature="sig-1",
            side=WalletTransaction.Side.BUY, amount_tokens=Decimal("1000"),
            amount_usd=Decimal("500"), occurred_at=timezone.now(),
        )

        activity = get_token_detail(token.id)["wallet_activity"]

        assert len(activity) == 1
        assert activity[0]["wallet_label"] == "Whale #1"
        assert activity[0]["classification"] == "smart_money"
        assert activity[0]["reputation_score"] == Decimal("89.00")
        assert activity[0]["amount_usd"] == Decimal("500")

    def test_state_reflects_the_latest_alert_event(self):
        token = TokenFactory()
        AlertEvent.objects.create(token=token, to_state=AlertState.BREAKOUT, triggered_at=timezone.now())
        assert get_token_detail(token.id)["overview"]["state"] == AlertState.BREAKOUT


@pytest.mark.django_db
class TestGetTokenHistory:
    def test_no_history_gives_empty_lists(self):
        token = TokenFactory()
        history = get_token_history(token.id)
        assert history["price"] == []
        assert history["holders"] == []

    def test_returns_points_within_the_window_oldest_first(self):
        token = TokenFactory()
        now = timezone.now()
        TokenSnapshot.objects.create(
            token=token, timestamp=now - timedelta(hours=1), price=Decimal("0.01")
        )
        TokenSnapshot.objects.create(token=token, timestamp=now, price=Decimal("0.02"))

        history = get_token_history(token.id, hours=24)

        assert len(history["price"]) == 2
        assert history["price"][0]["price"] == Decimal("0.01")
        assert history["price"][1]["price"] == Decimal("0.02")

    def test_excludes_points_outside_the_window(self):
        token = TokenFactory()
        TokenSnapshot.objects.create(
            token=token, timestamp=timezone.now() - timedelta(hours=48), price=Decimal("0.01")
        )

        history = get_token_history(token.id, hours=24)

        assert history["price"] == []

    def test_holder_history(self):
        token = TokenFactory()
        HolderSnapshot.objects.create(token=token, timestamp=timezone.now(), holder_count=400)

        history = get_token_history(token.id)

        assert history["holders"][0]["holder_count"] == 400

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.alerts.models import AlertEvent, AlertState
from apps.holders.models import HolderSnapshot
from apps.liquidity.models import LiquiditySnapshot
from apps.market_data.models import TokenSnapshot
from apps.narratives.factories import NarrativeFactory
from apps.narratives.models import TokenNarrative
from apps.scoring.models import TokenScore
from apps.tokens.factories import TokenFactory
from apps.tokens.services import get_live_feed
from apps.wallets.factories import WalletFactory
from apps.wallets.models import Wallet, WalletTransaction


def _fully_populated_token(**score_kwargs):
    token = TokenFactory()
    now = timezone.now()
    TokenSnapshot.objects.create(
        token=token, timestamp=now, price=Decimal("0.01"),
        market_cap=Decimal("100000"), volume_5m=Decimal("5000"),
    )
    LiquiditySnapshot.objects.create(token=token, timestamp=now, liquidity_usd=Decimal("40000"))
    HolderSnapshot.objects.create(token=token, timestamp=now, holder_count=300)
    defaults = {"opportunity_score": Decimal("60"), "risk_score": Decimal("20")}
    defaults.update(score_kwargs)
    TokenScore.objects.create(
        token=token, timestamp=now, score_2x=defaults["opportunity_score"],
        score_3x=defaults["opportunity_score"], momentum_score=Decimal("70"), **defaults,
    )
    return token


@pytest.mark.django_db
class TestGetLiveFeed:
    def test_no_tokens_returns_empty(self):
        assert get_live_feed() == []

    def test_inactive_tokens_are_excluded(self):
        TokenFactory(is_active=False)
        assert get_live_feed() == []

    def test_includes_a_row_per_active_token(self):
        _fully_populated_token()
        _fully_populated_token()
        assert len(get_live_feed()) == 2

    def test_row_contains_real_snapshot_data(self):
        token = _fully_populated_token()
        row = get_live_feed()[0]

        assert row["token_id"] == token.id
        assert row["market_cap"] == Decimal("100000")
        assert row["liquidity_usd"] == Decimal("40000")
        assert row["holder_count"] == 300
        assert row["momentum_score"] == Decimal("70.00")

    def test_token_with_no_score_has_none_fields_not_zero(self):
        TokenFactory()
        row = get_live_feed()[0]
        assert row["opportunity_score"] is None
        assert row["risk_score"] is None

    def test_state_defaults_to_discovered_without_alert_events(self):
        _fully_populated_token()
        row = get_live_feed()[0]
        assert row["state"] == "discovered"

    def test_state_reflects_the_latest_alert_event(self):
        token = _fully_populated_token()
        AlertEvent.objects.create(token=token, to_state=AlertState.WATCHING, triggered_at=timezone.now())
        row = get_live_feed()[0]
        assert row["state"] == AlertState.WATCHING

    def test_narrative_name_comes_from_the_top_ranked_link(self):
        token = _fully_populated_token()
        narrative = NarrativeFactory(name="Viral AI Meme")
        TokenNarrative.objects.create(
            token=token, narrative=narrative, relevance_score=Decimal("80"),
            detected_at=timezone.now(),
        )
        row = get_live_feed()[0]
        assert row["narrative_name"] == "Viral AI Meme"

    def test_smart_money_count_reflects_distinct_wallets(self):
        token = _fully_populated_token()
        wallet = WalletFactory(classification=Wallet.Classification.SMART_MONEY)
        WalletTransaction.objects.create(
            wallet=wallet, token=token, tx_signature="sig-1",
            side=WalletTransaction.Side.BUY, amount_tokens=Decimal("100"),
            occurred_at=timezone.now(),
        )
        row = get_live_feed()[0]
        assert row["smart_money_count"] == 1

    def test_ordering_is_applied(self):
        _fully_populated_token(opportunity_score=Decimal("30"))
        _fully_populated_token(opportunity_score=Decimal("90"))
        rows = get_live_feed(ordering="opportunity_score")
        assert [r["opportunity_score"] for r in rows] == [Decimal("30.00"), Decimal("90.00")]

    def test_state_filter_is_applied(self):
        watching = _fully_populated_token()
        AlertEvent.objects.create(
            token=watching, to_state=AlertState.WATCHING, triggered_at=timezone.now()
        )
        _fully_populated_token()  # stays "discovered"

        rows = get_live_feed(state="watching")

        assert len(rows) == 1
        assert rows[0]["token_id"] == watching.id

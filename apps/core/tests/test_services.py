from decimal import Decimal

import pytest
from django.utils import timezone

from apps.alerts.models import Alert, AlertEvent, AlertState
from apps.core.services import get_overview_stats
from apps.holders.models import HolderSnapshot
from apps.liquidity.models import LiquiditySnapshot
from apps.market_data.models import TokenSnapshot
from apps.outcomes.models import TokenOutcome
from apps.scoring.models import TokenScore
from apps.tokens.factories import TokenFactory
from apps.tokens.models import Token


def _candidate_token(**score_kwargs):
    token = TokenFactory()
    now = timezone.now()
    TokenSnapshot.objects.create(
        token=token, timestamp=now, price=Decimal("0.001"), volume_5m=Decimal("10000")
    )
    LiquiditySnapshot.objects.create(token=token, timestamp=now, liquidity_usd=Decimal("50000"))
    HolderSnapshot.objects.create(token=token, timestamp=now, holder_count=200)
    defaults = {"opportunity_score": Decimal("60"), "risk_score": Decimal("20")}
    defaults.update(score_kwargs)
    TokenScore.objects.create(
        token=token, timestamp=now, score_2x=defaults["opportunity_score"],
        score_3x=defaults["opportunity_score"], **defaults,
    )
    return token


@pytest.mark.django_db
class TestGetOverviewStats:
    def test_empty_system_returns_honest_zeros_and_nones(self):
        stats = get_overview_stats()
        assert stats["tokens_scanned_today"] == 0
        assert stats["candidates"] == 0
        assert stats["watchlist"] == 0
        assert stats["alerts_sent"] == 0
        assert stats["hit_rate_2x_pct"] is None
        assert stats["hit_rate_3x_pct"] is None

    def test_tokens_scanned_today_counts_todays_tokens_only(self):
        TokenFactory()
        TokenFactory()
        old = TokenFactory()
        # created_at is auto_now_add -- must overwrite via update(), not assign + save().
        Token.objects.filter(pk=old.pk).update(created_at=timezone.now() - timezone.timedelta(days=2))

        stats = get_overview_stats()
        assert stats["tokens_scanned_today"] == 2

    def test_candidates_counts_tokens_passing_the_config_gate(self):
        _candidate_token()  # default config is all-permissive (min thresholds 0)
        stats = get_overview_stats()
        assert stats["candidates"] == 1

    def test_watchlist_and_confirmed_reflect_latest_alert_event_state(self):
        watching_token = TokenFactory()
        AlertEvent.objects.create(
            token=watching_token, to_state=AlertState.WATCHING, triggered_at=timezone.now()
        )
        confirmed_token = TokenFactory()
        AlertEvent.objects.create(
            token=confirmed_token, to_state=AlertState.CONFIRMED, triggered_at=timezone.now()
        )

        stats = get_overview_stats()
        assert stats["watchlist"] == 1
        assert stats["confirmed"] == 1

    def test_only_the_most_recent_event_counts_per_token(self):
        token = TokenFactory()
        AlertEvent.objects.create(token=token, to_state=AlertState.WATCHING, triggered_at=timezone.now())
        AlertEvent.objects.create(
            token=token,
            to_state=AlertState.CONFIRMED,
            triggered_at=timezone.now() + timezone.timedelta(seconds=1),
        )

        stats = get_overview_stats()
        assert stats["watchlist"] == 0
        assert stats["confirmed"] == 1

    def test_alerts_sent_counts_all_alerts(self):
        token = TokenFactory()
        Alert.objects.create(token=token, state=AlertState.CONFIRMED, score=Decimal("80"))
        Alert.objects.create(token=token, state=AlertState.BREAKOUT, score=Decimal("90"))

        stats = get_overview_stats()
        assert stats["alerts_sent"] == 2

    def test_hit_rates_computed_once_outcomes_exist(self):
        token = TokenFactory()
        alert = Alert.objects.create(token=token, state=AlertState.CONFIRMED, score=Decimal("80"))
        TokenOutcome.objects.create(
            token=token, alert=alert, reference_timestamp=timezone.now(), initial_price="1",
            reached_2x=True, reached_3x=False,
        )
        other_token = TokenFactory()
        other_alert = Alert.objects.create(token=other_token, state=AlertState.CONFIRMED, score=Decimal("80"))
        TokenOutcome.objects.create(
            token=other_token, alert=other_alert, reference_timestamp=timezone.now(), initial_price="1",
            reached_2x=False, reached_3x=False,
        )

        stats = get_overview_stats()
        assert stats["hit_rate_2x_pct"] == 50.0
        assert stats["hit_rate_3x_pct"] == 0.0

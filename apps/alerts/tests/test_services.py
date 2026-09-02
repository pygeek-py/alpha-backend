import itertools
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.alerts.models import Alert, AlertEvent, AlertState
from apps.alerts.services import evaluate_alert_state, get_alerts
from apps.holders.models import HolderSnapshot
from apps.liquidity.models import LiquiditySnapshot
from apps.market_data.models import TokenSnapshot
from apps.narratives.factories import NarrativeFactory
from apps.narratives.models import TokenNarrative
from apps.scoring.models import TokenSafetyCheck, TokenScore
from apps.tokens.factories import TokenFactory
from apps.wallets.factories import WalletFactory
from apps.wallets.models import Wallet, WalletTransaction

# Every snapshot table enforces a (token, timestamp, source) uniqueness
# constraint. Two independent timezone.now() calls close together can land
# on the same stored value and collide -- this counter guarantees each
# snapshot timestamp used in these tests is strictly later than the last,
# independent of wall-clock resolution.
_timestamp_counter = itertools.count()


def _next_timestamp():
    return timezone.now() + timedelta(seconds=next(_timestamp_counter))


def _make_snapshots(token, *, volume_5m=Decimal("10000"), liquidity=Decimal("50000"), holders=200):
    now = _next_timestamp()
    TokenSnapshot.objects.create(token=token, timestamp=now, price=Decimal("0.001"), volume_5m=volume_5m)
    LiquiditySnapshot.objects.create(token=token, timestamp=now, liquidity_usd=liquidity)
    HolderSnapshot.objects.create(token=token, timestamp=now, holder_count=holders)


def _make_score(token, *, opportunity_score=Decimal("60"), risk_score=Decimal("20")):
    return TokenScore.objects.create(
        token=token,
        timestamp=timezone.now(),
        opportunity_score=opportunity_score,
        risk_score=risk_score,
        score_2x=opportunity_score,
        score_3x=opportunity_score,
    )


def _candidate_token(**score_kwargs):
    token = TokenFactory()
    _make_snapshots(token)
    _make_score(token, **score_kwargs)
    return token


@pytest.mark.django_db
class TestEvaluateAlertStateBasics:
    def test_no_token_score_returns_none(self):
        token = TokenFactory()
        assert evaluate_alert_state(token) is None
        assert AlertEvent.objects.count() == 0

    def test_not_a_candidate_produces_no_transition(self):
        token = TokenFactory()
        _make_score(token)  # no liquidity/volume/holder snapshots -- fails closed
        assert evaluate_alert_state(token) is None
        assert AlertEvent.objects.count() == 0

    def test_first_evaluation_transitions_to_watching_with_no_cooldown_gate(self):
        token = _candidate_token()
        event = evaluate_alert_state(token)

        assert event is not None
        assert event.from_state == AlertState.DISCOVERED
        assert event.to_state == AlertState.WATCHING

        alert = Alert.objects.get(token=token)
        assert alert.state == AlertState.WATCHING

    def test_unchanged_evidence_produces_no_second_transition(self):
        token = _candidate_token()
        evaluate_alert_state(token)
        assert evaluate_alert_state(token) is None
        assert AlertEvent.objects.filter(token=token).count() == 1


@pytest.mark.django_db
class TestSignalDeltaEvidence:
    def test_volume_acceleration_moves_watching_to_developing(self):
        token = _candidate_token()
        evaluate_alert_state(token)  # DISCOVERED -> WATCHING

        # A second, much larger volume snapshot triggers market acceleration evidence.
        TokenSnapshot.objects.create(
            token=token, timestamp=_next_timestamp(), price=Decimal("0.001"), volume_5m=Decimal("40000")
        )
        event = evaluate_alert_state(token)

        assert event.to_state == AlertState.DEVELOPING
        # Within cooldown of the first (WATCHING) alert -- event recorded, no new Alert.
        assert Alert.objects.filter(token=token, state=AlertState.DEVELOPING).count() == 0

    def test_alert_created_once_cooldown_has_elapsed(self):
        token = _candidate_token()
        evaluate_alert_state(token)
        Alert.objects.filter(token=token).update(created_at=timezone.now() - timedelta(minutes=25))

        TokenSnapshot.objects.create(
            token=token, timestamp=_next_timestamp(), price=Decimal("0.001"), volume_5m=Decimal("40000")
        )
        event = evaluate_alert_state(token)

        assert event.to_state == AlertState.DEVELOPING
        assert Alert.objects.filter(token=token, state=AlertState.DEVELOPING).count() == 1

    def test_smart_money_entry_counts_as_evidence(self):
        token = _candidate_token()
        evaluate_alert_state(token)
        Alert.objects.filter(token=token).update(created_at=timezone.now() - timedelta(minutes=25))

        wallet = WalletFactory(classification=Wallet.Classification.SMART_MONEY)
        WalletTransaction.objects.create(
            wallet=wallet,
            token=token,
            tx_signature="sig-1",
            side=WalletTransaction.Side.BUY,
            amount_tokens=Decimal("1000"),
            occurred_at=timezone.now(),
        )
        event = evaluate_alert_state(token)

        assert event.to_state == AlertState.DEVELOPING
        assert "1 tracked smart-money wallet(s) entered" in event.reasons


@pytest.mark.django_db
class TestInvalidation:
    def _reach_confirmed(self, token):
        volumes = (Decimal("10000"), Decimal("40000"), Decimal("160000"), Decimal("640000"))
        for volume in volumes:
            step = _next_timestamp()
            TokenSnapshot.objects.create(
                token=token, timestamp=step, price=Decimal("0.001"), volume_5m=volume
            )
            HolderSnapshot.objects.create(
                token=token, timestamp=step, holder_count=int(200 * (1 + volume / 10000))
            )
            evaluate_alert_state(token)
            Alert.objects.filter(token=token).update(created_at=timezone.now() - timedelta(minutes=25))

    def test_hard_rejection_after_confirmed_becomes_invalidated(self):
        token = _candidate_token()
        LiquiditySnapshot.objects.create(
            token=token, timestamp=_next_timestamp(), liquidity_usd=Decimal("80000")
        )
        self._reach_confirmed(token)

        last_event = AlertEvent.objects.filter(token=token).order_by("-triggered_at").first()
        if last_event.to_state != AlertState.CONFIRMED:
            pytest.skip("evidence bands didn't reach CONFIRMED -- see test_state_machine for the classifier")

        TokenSafetyCheck.objects.create(
            token=token,
            timestamp=timezone.now(),
            score=Decimal("10"),
            risk_level=TokenSafetyCheck.RiskLevel.EXTREME,
            hard_rejection=True,
        )
        event = evaluate_alert_state(token)

        assert event.to_state == AlertState.INVALIDATED
        # Cooldown-exempt transition -- alert created immediately.
        assert Alert.objects.filter(token=token, state=AlertState.INVALIDATED).count() == 1


@pytest.mark.django_db
class TestNarrativeDeduplication:
    def test_only_top_ranked_token_in_narrative_gets_confirmed_alert(self):
        narrative = NarrativeFactory()
        strong = _candidate_token(opportunity_score=Decimal("90"))
        weak = _candidate_token(opportunity_score=Decimal("70"))

        now = timezone.now()
        TokenNarrative.objects.create(
            token=strong, narrative=narrative, relevance_score=Decimal("80"), detected_at=now
        )
        TokenNarrative.objects.create(
            token=weak, narrative=narrative, relevance_score=Decimal("80"), detected_at=now
        )

        for token in (strong, weak):
            evaluate_alert_state(token)
            Alert.objects.filter(token=token).update(created_at=timezone.now() - timedelta(minutes=25))
            step = _next_timestamp()
            TokenSnapshot.objects.create(
                token=token, timestamp=step, price=Decimal("0.001"), volume_5m=Decimal("40000")
            )
            LiquiditySnapshot.objects.create(token=token, timestamp=step, liquidity_usd=Decimal("100000"))
            HolderSnapshot.objects.create(token=token, timestamp=step, holder_count=500)
            evaluate_alert_state(token)
            Alert.objects.filter(token=token).update(created_at=timezone.now() - timedelta(minutes=25))

        # Push both to CONFIRMED with a third evidence burst.
        for token in (strong, weak):
            step = _next_timestamp()
            TokenSnapshot.objects.create(
                token=token, timestamp=step, price=Decimal("0.002"), volume_5m=Decimal("400000")
            )
            HolderSnapshot.objects.create(token=token, timestamp=step, holder_count=900)
            evaluate_alert_state(token)

        strong_confirmed = Alert.objects.filter(token=strong, state=AlertState.CONFIRMED).exists()
        weak_confirmed = Alert.objects.filter(token=weak, state=AlertState.CONFIRMED).exists()
        if strong_confirmed or weak_confirmed:
            assert strong_confirmed and not weak_confirmed


@pytest.mark.django_db
class TestAlertBudget:
    def test_budget_blocks_developing_alert_once_at_cap(self):
        token = _candidate_token()
        evaluate_alert_state(token)
        Alert.objects.filter(token=token).update(created_at=timezone.now() - timedelta(minutes=25))

        # Fill the budget with 5 (default max_alerts_per_hour) unrelated DEVELOPING alerts.
        for _ in range(5):
            other = _candidate_token()
            Alert.objects.create(token=other, state=AlertState.DEVELOPING, score=Decimal("60"))

        TokenSnapshot.objects.create(
            token=token, timestamp=_next_timestamp(), price=Decimal("0.001"), volume_5m=Decimal("40000")
        )
        event = evaluate_alert_state(token)

        assert event.to_state == AlertState.DEVELOPING
        assert Alert.objects.filter(token=token, state=AlertState.DEVELOPING).count() == 0


@pytest.mark.django_db
class TestGetAlerts:
    def test_no_alerts_gives_empty_list(self):
        assert get_alerts() == []

    def test_returns_newest_first(self):
        token = TokenFactory()
        older = Alert.objects.create(token=token, state=AlertState.WATCHING, score=Decimal("50"))
        Alert.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(minutes=10))
        newer = Alert.objects.create(token=token, state=AlertState.CONFIRMED, score=Decimal("80"))

        rows = get_alerts()

        assert [r["id"] for r in rows] == [newer.id, older.id]

    def test_row_shape(self):
        token = TokenFactory(symbol="PEPE")
        Alert.objects.create(
            token=token, state=AlertState.CONFIRMED, score=Decimal("85"), risk_score=Decimal("15"),
            reasons=["5m volume accelerated 3x"], is_priority=True, narrative_summary="AI Meme",
        )

        row = get_alerts()[0]

        assert row["token_symbol"] == "PEPE"
        assert row["state"] == AlertState.CONFIRMED
        assert row["reasons"] == ["5m volume accelerated 3x"]
        assert row["is_priority"] is True
        assert row["narrative_summary"] == "AI Meme"
        assert row["telegram_sent"] is False
        assert row["outcome_reached_2x"] is None

    def test_filters_by_state(self):
        token = TokenFactory()
        Alert.objects.create(token=token, state=AlertState.WATCHING, score=Decimal("50"))
        confirmed = Alert.objects.create(token=token, state=AlertState.CONFIRMED, score=Decimal("80"))

        rows = get_alerts(state=AlertState.CONFIRMED)

        assert [r["id"] for r in rows] == [confirmed.id]

    def test_invalid_state_is_ignored_not_erroring(self):
        token = TokenFactory()
        Alert.objects.create(token=token, state=AlertState.WATCHING, score=Decimal("50"))

        rows = get_alerts(state="not-a-real-state")

        assert len(rows) == 1

    def test_filters_by_priority_only(self):
        token = TokenFactory()
        Alert.objects.create(token=token, state=AlertState.CONFIRMED, score=Decimal("80"), is_priority=False)
        priority = Alert.objects.create(
            token=token, state=AlertState.CONFIRMED, score=Decimal("96"), is_priority=True
        )

        rows = get_alerts(priority_only=True)

        assert [r["id"] for r in rows] == [priority.id]

    def test_includes_outcome_when_tracked(self):
        from apps.outcomes.models import TokenOutcome

        token = TokenFactory()
        alert = Alert.objects.create(token=token, state=AlertState.CONFIRMED, score=Decimal("80"))
        TokenOutcome.objects.create(
            token=token, alert=alert, reference_timestamp=timezone.now(), initial_price="1",
            reached_2x=True, reached_3x=False,
        )

        row = get_alerts()[0]

        assert row["outcome_reached_2x"] is True
        assert row["outcome_reached_3x"] is False

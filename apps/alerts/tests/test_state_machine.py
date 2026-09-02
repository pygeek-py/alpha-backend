from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.alerts.models import AlertState
from apps.alerts.state_machine import (
    SignalEvidence,
    classify_state,
    gather_signal_reasons,
    is_priority_opportunity,
    is_top_ranked_candidate,
    is_under_alert_budget,
    should_alert,
)


class TestGatherSignalReasons:
    def test_no_signals_gives_zero_evidence(self):
        evidence = gather_signal_reasons()
        assert evidence.category_count == 0
        assert evidence.reasons == []

    def test_each_nonempty_category_counts_once(self):
        evidence = gather_signal_reasons(
            market_signals=["5m volume accelerated 3x", "Price broke resistance"],
            liquidity_signals=["Liquidity grew 50%"],
        )
        assert evidence.category_count == 2
        assert len(evidence.reasons) == 3

    def test_smart_money_entry_counts_as_a_category(self):
        evidence = gather_signal_reasons(smart_money_entries=2)
        assert evidence.category_count == 1
        assert "2 tracked smart-money wallet(s) entered" in evidence.reasons

    def test_narrative_momentum_below_threshold_does_not_count(self):
        evidence = gather_signal_reasons(narrative_momentum_score=Decimal("60"))
        assert evidence.category_count == 0

    def test_narrative_momentum_at_or_above_threshold_counts(self):
        evidence = gather_signal_reasons(narrative_momentum_score=Decimal("65"))
        assert evidence.category_count == 1

    def test_all_five_categories_can_fire_together(self):
        evidence = gather_signal_reasons(
            market_signals=["a"],
            liquidity_signals=["b"],
            holder_signals=["c"],
            smart_money_entries=1,
            narrative_momentum_score=Decimal("90"),
        )
        assert evidence.category_count == 5


def _evidence(count: int) -> SignalEvidence:
    return SignalEvidence(reasons=[f"reason {i}" for i in range(count)], category_count=count)


class TestClassifyState:
    def test_not_a_candidate_holds_at_discovered(self):
        result = classify_state(
            current_state=AlertState.DISCOVERED,
            is_candidate=False,
            hard_rejection=False,
            evidence=_evidence(0),
            opportunity_score=Decimal("50"),
        )
        assert result == AlertState.DISCOVERED

    def test_candidate_with_no_evidence_becomes_watching(self):
        result = classify_state(
            current_state=AlertState.DISCOVERED,
            is_candidate=True,
            hard_rejection=False,
            evidence=_evidence(0),
            opportunity_score=Decimal("50"),
        )
        assert result == AlertState.WATCHING

    def test_one_evidence_category_becomes_developing(self):
        result = classify_state(
            current_state=AlertState.WATCHING,
            is_candidate=True,
            hard_rejection=False,
            evidence=_evidence(1),
            opportunity_score=Decimal("60"),
        )
        assert result == AlertState.DEVELOPING

    def test_three_evidence_categories_becomes_confirmed(self):
        result = classify_state(
            current_state=AlertState.DEVELOPING,
            is_candidate=True,
            hard_rejection=False,
            evidence=_evidence(3),
            opportunity_score=Decimal("80"),
        )
        assert result == AlertState.CONFIRMED

    def test_never_regresses_below_last_reached_state(self):
        """Evidence dropping to zero after reaching DEVELOPING must not
        revert to WATCHING -- PRD S30 draws no backward path pre-CONFIRMED."""
        result = classify_state(
            current_state=AlertState.DEVELOPING,
            is_candidate=True,
            hard_rejection=False,
            evidence=_evidence(0),
            opportunity_score=Decimal("55"),
        )
        assert result == AlertState.DEVELOPING

    def test_hard_rejection_holds_at_current_state_pre_confirmation(self):
        result = classify_state(
            current_state=AlertState.WATCHING,
            is_candidate=True,
            hard_rejection=True,
            evidence=_evidence(3),
            opportunity_score=Decimal("80"),
        )
        assert result == AlertState.WATCHING

    def test_confirmed_with_strong_new_evidence_becomes_breakout(self):
        result = classify_state(
            current_state=AlertState.CONFIRMED,
            is_candidate=True,
            hard_rejection=False,
            evidence=_evidence(4),
            opportunity_score=Decimal("90"),
            previous_confirmed_opportunity_score=Decimal("85"),
        )
        assert result == AlertState.BREAKOUT

    def test_confirmed_stays_confirmed_without_breakout_evidence(self):
        result = classify_state(
            current_state=AlertState.CONFIRMED,
            is_candidate=True,
            hard_rejection=False,
            evidence=_evidence(3),
            opportunity_score=Decimal("85"),
            previous_confirmed_opportunity_score=Decimal("85"),
        )
        assert result == AlertState.CONFIRMED

    def test_confirmed_with_hard_rejection_becomes_invalidated(self):
        result = classify_state(
            current_state=AlertState.CONFIRMED,
            is_candidate=True,
            hard_rejection=True,
            evidence=_evidence(0),
            opportunity_score=Decimal("40"),
            previous_confirmed_opportunity_score=Decimal("85"),
        )
        assert result == AlertState.INVALIDATED

    def test_confirmed_with_no_longer_a_candidate_becomes_invalidated(self):
        result = classify_state(
            current_state=AlertState.CONFIRMED,
            is_candidate=False,
            hard_rejection=False,
            evidence=_evidence(0),
            opportunity_score=Decimal("60"),
            previous_confirmed_opportunity_score=Decimal("85"),
        )
        assert result == AlertState.INVALIDATED

    def test_confirmed_with_large_score_drop_becomes_invalidated(self):
        result = classify_state(
            current_state=AlertState.CONFIRMED,
            is_candidate=True,
            hard_rejection=False,
            evidence=_evidence(1),
            opportunity_score=Decimal("60"),
            previous_confirmed_opportunity_score=Decimal("85"),
        )
        assert result == AlertState.INVALIDATED

    def test_confirmed_with_small_score_drop_stays_confirmed(self):
        result = classify_state(
            current_state=AlertState.CONFIRMED,
            is_candidate=True,
            hard_rejection=False,
            evidence=_evidence(1),
            opportunity_score=Decimal("80"),
            previous_confirmed_opportunity_score=Decimal("85"),
        )
        assert result == AlertState.CONFIRMED

    def test_breakout_can_be_invalidated(self):
        result = classify_state(
            current_state=AlertState.BREAKOUT,
            is_candidate=False,
            hard_rejection=False,
            evidence=_evidence(0),
            opportunity_score=Decimal("50"),
        )
        assert result == AlertState.INVALIDATED

    def test_invalidated_is_terminal(self):
        result = classify_state(
            current_state=AlertState.INVALIDATED,
            is_candidate=True,
            hard_rejection=False,
            evidence=_evidence(5),
            opportunity_score=Decimal("95"),
        )
        assert result == AlertState.INVALIDATED


class TestShouldAlert:
    def test_no_state_change_never_alerts(self):
        assert should_alert(
            previous_state=AlertState.WATCHING,
            new_state=AlertState.WATCHING,
            last_alert_at=None,
            now=timezone.now(),
            cooldown_minutes=20,
        ) is False

    def test_first_ever_alert_is_not_blocked_by_cooldown(self):
        assert should_alert(
            previous_state=AlertState.WATCHING,
            new_state=AlertState.DEVELOPING,
            last_alert_at=None,
            now=timezone.now(),
            cooldown_minutes=20,
        ) is True

    def test_within_cooldown_blocks_ordinary_transition(self):
        now = timezone.now()
        assert should_alert(
            previous_state=AlertState.WATCHING,
            new_state=AlertState.DEVELOPING,
            last_alert_at=now - timedelta(minutes=5),
            now=now,
            cooldown_minutes=20,
        ) is False

    def test_past_cooldown_allows_alert(self):
        now = timezone.now()
        assert should_alert(
            previous_state=AlertState.WATCHING,
            new_state=AlertState.DEVELOPING,
            last_alert_at=now - timedelta(minutes=25),
            now=now,
            cooldown_minutes=20,
        ) is True

    def test_confirmed_to_breakout_exempt_from_cooldown(self):
        now = timezone.now()
        assert should_alert(
            previous_state=AlertState.CONFIRMED,
            new_state=AlertState.BREAKOUT,
            last_alert_at=now - timedelta(minutes=1),
            now=now,
            cooldown_minutes=20,
        ) is True

    def test_confirmed_to_invalidated_exempt_from_cooldown(self):
        now = timezone.now()
        assert should_alert(
            previous_state=AlertState.CONFIRMED,
            new_state=AlertState.INVALIDATED,
            last_alert_at=now - timedelta(minutes=1),
            now=now,
            cooldown_minutes=20,
        ) is True

    def test_watching_to_developing_not_exempt(self):
        now = timezone.now()
        assert should_alert(
            previous_state=AlertState.WATCHING,
            new_state=AlertState.DEVELOPING,
            last_alert_at=now - timedelta(minutes=1),
            now=now,
            cooldown_minutes=20,
        ) is False

    def test_priority_bypasses_cooldown(self):
        now = timezone.now()
        assert should_alert(
            previous_state=AlertState.WATCHING,
            new_state=AlertState.DEVELOPING,
            last_alert_at=now - timedelta(minutes=1),
            now=now,
            cooldown_minutes=20,
            is_priority=True,
        ) is True


class TestIsPriorityOpportunity:
    def test_all_conditions_met_is_priority(self):
        assert is_priority_opportunity(
            opportunity_score=Decimal("96"),
            risk_score=Decimal("15"),
            narrative_momentum_score=Decimal("80"),
            smart_money_entries=1,
        ) is True

    def test_score_at_threshold_not_priority(self):
        assert is_priority_opportunity(
            opportunity_score=Decimal("95"),
            risk_score=Decimal("15"),
            narrative_momentum_score=Decimal("80"),
            smart_money_entries=1,
        ) is False

    def test_high_risk_disqualifies(self):
        assert is_priority_opportunity(
            opportunity_score=Decimal("96"),
            risk_score=Decimal("25"),
            narrative_momentum_score=Decimal("80"),
            smart_money_entries=1,
        ) is False

    def test_no_smart_money_disqualifies(self):
        assert is_priority_opportunity(
            opportunity_score=Decimal("96"),
            risk_score=Decimal("15"),
            narrative_momentum_score=Decimal("80"),
            smart_money_entries=0,
        ) is False

    def test_missing_scores_never_priority(self):
        assert is_priority_opportunity(
            opportunity_score=None,
            risk_score=Decimal("15"),
            narrative_momentum_score=Decimal("80"),
            smart_money_entries=1,
        ) is False


class TestIsTopRankedCandidate:
    def test_empty_ranking_does_not_block(self):
        assert is_top_ranked_candidate(token_id=1, ranked_token_ids=[]) is True

    def test_top_ranked_passes(self):
        assert is_top_ranked_candidate(token_id=1, ranked_token_ids=[1, 2, 3]) is True

    def test_not_top_ranked_is_blocked(self):
        assert is_top_ranked_candidate(token_id=2, ranked_token_ids=[1, 2, 3]) is False


class TestIsUnderAlertBudget:
    def test_under_budget_passes(self):
        assert is_under_alert_budget(alerts_in_last_hour=2, max_alerts_per_hour=5, is_priority=False) is True

    def test_at_budget_blocks(self):
        assert is_under_alert_budget(alerts_in_last_hour=5, max_alerts_per_hour=5, is_priority=False) is False

    def test_priority_bypasses_budget(self):
        assert is_under_alert_budget(alerts_in_last_hour=5, max_alerts_per_hour=5, is_priority=True) is True

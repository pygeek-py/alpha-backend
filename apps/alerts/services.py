from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.alerts.models import Alert, AlertEvent, AlertState
from apps.alerts.state_machine import (
    BUDGET_GATED_STATES,
    NARRATIVE_DEDUP_STATES,
    SMART_MONEY_ENTRY_WINDOW_MINUTES,
    classify_state,
    gather_signal_reasons,
    is_priority_opportunity,
    is_top_ranked_candidate,
    is_under_alert_budget,
    should_alert,
)
from apps.configuration.services import config_to_dict, get_current_configuration
from apps.configuration.simulation import CandidateSnapshot, passes_configuration
from apps.holders.services import get_holder_features
from apps.liquidity.services import get_liquidity_features
from apps.market_data.services import get_market_features
from apps.tokens.models import Token
from apps.wallets.models import Wallet, WalletTransaction


def _latest_candidate_snapshot(token: Token, opportunity_score, risk_score) -> CandidateSnapshot:
    liquidity = token.liquidity_snapshots.order_by("-timestamp").first()
    volume = token.snapshots.order_by("-timestamp").first()
    holders = token.holder_snapshots.order_by("-timestamp").first()
    return CandidateSnapshot(
        opportunity_score=opportunity_score,
        risk_score=risk_score,
        liquidity_usd=liquidity.liquidity_usd if liquidity else None,
        volume_5m_usd=volume.volume_5m if volume else None,
        holder_count=holders.holder_count if holders else None,
    )


def _count_smart_money_entries(token: Token, *, since) -> int:
    return (
        WalletTransaction.objects.filter(
            token=token,
            wallet__classification=Wallet.Classification.SMART_MONEY,
            occurred_at__gte=since,
        )
        .values("wallet_id")
        .distinct()
        .count()
    )


def _narrative_momentum_score(token: Token) -> Decimal | None:
    scores = [
        link.momentum_score for link in token.narrative_links.all() if link.momentum_score is not None
    ]
    return max(scores) if scores else None


def _top_narrative_name(token: Token) -> str:
    top_link = (
        token.narrative_links.select_related("narrative")
        .order_by("-relevance_score")
        .first()
    )
    return top_link.narrative.name if top_link else ""


def _ranked_competing_token_ids(token: Token) -> list[int]:
    """Tokens sharing any of `token`'s narratives, ranked by their latest
    opportunity_score descending (PRD S22: rank instead of alerting on every
    token in a crowded narrative). Unlike apps.narratives.services's
    rank_tokens_in_narrative (which ranks by narrative relevance), alert
    deduplication needs to rank by opportunity -- the PRD S22 example ranks
    $AAA/$BBB/$CCC by Score, not by how relevant each is to the narrative.
    """
    narrative_ids = list(token.narrative_links.values_list("narrative_id", flat=True))
    if not narrative_ids:
        return []

    competing_token_ids = set(
        Token.objects.filter(
            narrative_links__narrative_id__in=narrative_ids, is_active=True
        ).values_list("id", flat=True)
    )
    competing_token_ids.add(token.id)

    scored = []
    for competing_id in competing_token_ids:
        latest = (
            Token.objects.get(pk=competing_id)
            .scores.order_by("-timestamp")
            .values_list("opportunity_score", flat=True)
            .first()
        )
        if latest is not None:
            scored.append((competing_id, latest))

    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [token_id for token_id, _ in scored]


def _alerts_in_last_hour(now) -> int:
    return Alert.objects.filter(
        created_at__gte=now - timedelta(hours=1), state__in=BUDGET_GATED_STATES
    ).count()


def evaluate_alert_state(token: Token) -> AlertEvent | None:
    """Runs one evaluation cycle for `token`: computes the state its current
    evidence justifies, and if that's a real transition, records an
    AlertEvent and -- subject to cooldown/budget/narrative-dedup -- a
    user-facing Alert. Returns None if there's no TokenScore yet to evaluate
    against, or if evidence doesn't justify a state change.
    """
    current_score = token.scores.order_by("-timestamp").first()
    if current_score is None:
        return None

    now = timezone.now()
    safety_check = token.safety_checks.order_by("-timestamp").first()
    hard_rejection = safety_check.hard_rejection if safety_check else False

    config = get_current_configuration()
    config_dict = config_to_dict(config)
    candidate = _latest_candidate_snapshot(token, current_score.opportunity_score, current_score.risk_score)
    is_candidate = passes_configuration(candidate, config_dict)

    market_features = get_market_features(token)
    liquidity_features = get_liquidity_features(token)
    holder_features = get_holder_features(token)
    smart_money_entries = _count_smart_money_entries(
        token, since=now - timedelta(minutes=SMART_MONEY_ENTRY_WINDOW_MINUTES)
    )
    narrative_momentum_score = _narrative_momentum_score(token)

    evidence = gather_signal_reasons(
        market_signals=market_features.signals if market_features else [],
        liquidity_signals=liquidity_features.signals if liquidity_features else [],
        holder_signals=holder_features.signals if holder_features else [],
        smart_money_entries=smart_money_entries,
        narrative_momentum_score=narrative_momentum_score,
    )

    last_event = token.alert_events.order_by("-triggered_at").first()
    current_recorded_state = last_event.to_state if last_event else AlertState.DISCOVERED

    last_confirmed_alert = (
        token.alerts.filter(state__in=[AlertState.CONFIRMED, AlertState.BREAKOUT])
        .order_by("-created_at")
        .first()
    )
    previous_confirmed_opportunity_score = last_confirmed_alert.score if last_confirmed_alert else None

    new_state = classify_state(
        current_state=current_recorded_state,
        is_candidate=is_candidate,
        hard_rejection=hard_rejection,
        evidence=evidence,
        opportunity_score=current_score.opportunity_score,
        previous_confirmed_opportunity_score=previous_confirmed_opportunity_score,
    )

    if new_state == current_recorded_state:
        return None

    event = AlertEvent.objects.create(
        token=token,
        from_state=current_recorded_state,
        to_state=new_state,
        score=current_score.opportunity_score,
        reasons=evidence.reasons,
        triggered_at=now,
    )

    if new_state != AlertState.DISCOVERED:
        _maybe_create_alert(
            token=token,
            event=event,
            new_state=new_state,
            previous_state=current_recorded_state,
            current_score=current_score,
            evidence=evidence,
            narrative_momentum_score=narrative_momentum_score,
            smart_money_entries=smart_money_entries,
            config=config,
            now=now,
        )

    return event


def _maybe_create_alert(
    *, token, event, new_state, previous_state, current_score, evidence,
    narrative_momentum_score, smart_money_entries, config, now,
) -> Alert | None:
    is_priority = is_priority_opportunity(
        opportunity_score=current_score.opportunity_score,
        risk_score=current_score.risk_score,
        narrative_momentum_score=narrative_momentum_score,
        smart_money_entries=smart_money_entries,
    )

    if new_state != AlertState.WATCHING:
        last_alert = token.alerts.order_by("-created_at").first()
        last_alert_at = last_alert.created_at if last_alert else None
        if not should_alert(
            previous_state=previous_state,
            new_state=new_state,
            last_alert_at=last_alert_at,
            now=now,
            cooldown_minutes=config.alert_cooldown_minutes,
            is_priority=is_priority,
        ):
            return None

        if new_state in BUDGET_GATED_STATES and not is_under_alert_budget(
            alerts_in_last_hour=_alerts_in_last_hour(now),
            max_alerts_per_hour=config.max_alerts_per_hour,
            is_priority=is_priority,
        ):
            return None

        if new_state in NARRATIVE_DEDUP_STATES:
            ranked_ids = _ranked_competing_token_ids(token)
            if not is_top_ranked_candidate(token_id=token.id, ranked_token_ids=ranked_ids):
                return None

    # Batch 12 (Prediction Engine) hasn't shipped yet -- if a Prediction
    # nonetheless exists (e.g. manually created), attach and surface its
    # probabilities honestly; otherwise these stay None, not fabricated.
    latest_prediction = token.predictions.order_by("-timestamp").first()

    return Alert.objects.create(
        token=token,
        alert_event=event,
        prediction=latest_prediction,
        state=new_state,
        score=current_score.opportunity_score,
        risk_score=current_score.risk_score,
        probability_2x=latest_prediction.probability_2x if latest_prediction else None,
        probability_3x=latest_prediction.probability_3x if latest_prediction else None,
        narrative_summary=_top_narrative_name(token),
        reasons=evidence.reasons,
        is_priority=is_priority,
    )


VALID_ALERT_STATES = {choice[0] for choice in AlertState.choices}


def get_alerts(*, state: str | None = None, priority_only: bool = False, limit: int = 200) -> list[dict]:
    """PRD S50/S57: the alert feed -- newest first, with each alert's "why
    now" reasons and Telegram delivery status, plus outcome status where
    tracking has started (Batch 11)."""
    queryset = Alert.objects.select_related("token", "outcome").order_by("-created_at")
    if state and state in VALID_ALERT_STATES:
        queryset = queryset.filter(state=state)
    if priority_only:
        queryset = queryset.filter(is_priority=True)

    rows = []
    for alert in queryset[:limit]:
        outcome = getattr(alert, "outcome", None)
        rows.append(
            {
                "id": alert.id,
                "token_id": alert.token_id,
                "token_symbol": alert.token.symbol or alert.token.address[:8],
                "token_address": alert.token.address,
                "state": alert.state,
                "score": alert.score,
                "risk_score": alert.risk_score,
                "probability_2x": alert.probability_2x,
                "probability_3x": alert.probability_3x,
                "narrative_summary": alert.narrative_summary,
                "reasons": alert.reasons,
                "is_priority": alert.is_priority,
                "telegram_sent": alert.telegram_sent,
                "telegram_sent_at": alert.telegram_sent_at,
                "created_at": alert.created_at,
                "outcome_reached_2x": outcome.reached_2x if outcome else None,
                "outcome_reached_3x": outcome.reached_3x if outcome else None,
            }
        )
    return rows

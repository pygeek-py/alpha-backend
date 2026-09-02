"""Alert state machine, signal-delta evidence, and anti-spam gating (PRD
S30-37). Pure functions -- every input is an explicit value, never queried
here (see apps/alerts/services.py for that).

Signal-delta reasons are not recomputed from scratch: they're assembled from
the `.signals` lists that apps/market_data, apps/liquidity, and apps/holders
already produce when comparing a token's current snapshot against its
previous one (Batches 5-6) -- e.g. "5m volume accelerated 4.2x". This keeps
the "why now" vocabulary (PRD S32, S37) grounded in the same acceleration
math those apps already validated, rather than a second, divergent
implementation living here.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from apps.alerts.models import AlertState

# How many distinct evidence categories must be firing to justify each band.
# A deterministic V1 rule set (PRD S23: "weights must eventually become
# configurable and data-driven") -- not one of Batch 9's AI-tuned
# ANALYZABLE_FIELDS today, but a reasonable future extension point.
DEVELOPING_MIN_EVIDENCE = 1
CONFIRMED_MIN_EVIDENCE = 3
BREAKOUT_MIN_EVIDENCE = 4

# A previously CONFIRMED/BREAKOUT token whose opportunity score drops by at
# least this many points is considered to have broken down (PRD S30 INVALIDATED).
INVALIDATION_SCORE_DROP = Decimal("20")

# Momentum is centered at 50 (no change) -- see apps/narratives/scoring.py.
NARRATIVE_MOMENTUM_ACCELERATION_THRESHOLD = Decimal("65")
SMART_MONEY_ENTRY_WINDOW_MINUTES = 30

# PRD S11's own "Low risk" band (0-20) -- reused verbatim for the S35
# priority-override's "Low risk" condition rather than inventing a new bar.
PRIORITY_MIN_OPPORTUNITY_SCORE = Decimal("95")
PRIORITY_MAX_RISK_SCORE = Decimal("20")

# States from which INVALIDATED is reachable (PRD S33's stated exceptions).
INVALIDATABLE_STATES = {AlertState.CONFIRMED, AlertState.BREAKOUT}

# Cooldown-exempt transitions (PRD S33: "Possible exceptions").
COOLDOWN_EXEMPT_TRANSITIONS = {
    (AlertState.CONFIRMED, AlertState.BREAKOUT),
    (AlertState.CONFIRMED, AlertState.INVALIDATED),
    (AlertState.BREAKOUT, AlertState.INVALIDATED),
}

# Forward progression order for the pre-CONFIRMED candidate lifecycle.
STATE_ORDER = [
    AlertState.DISCOVERED,
    AlertState.WATCHING,
    AlertState.DEVELOPING,
    AlertState.CONFIRMED,
    AlertState.BREAKOUT,
]

# Alert levels the system-wide alert budget (PRD S35) counts against. WATCH
# is "dashboard only" (S36) and therefore unlimited; INVALIDATED is risk
# information about an already-alerted token and must never be silently
# dropped for being over budget.
BUDGET_GATED_STATES = {AlertState.DEVELOPING, AlertState.CONFIRMED, AlertState.BREAKOUT}

# Narrative deduplication (PRD S22/S34) only gates the state that actually
# competes for a fresh "strongest candidate" ranking. BREAKOUT is a
# continuation of an already-deduplicated CONFIRMED candidate, not a new
# entrant into the ranking.
NARRATIVE_DEDUP_STATES = {AlertState.CONFIRMED}


@dataclass
class SignalEvidence:
    reasons: list[str] = field(default_factory=list)
    category_count: int = 0


def gather_signal_reasons(
    *,
    market_signals: list[str] = (),
    liquidity_signals: list[str] = (),
    holder_signals: list[str] = (),
    smart_money_entries: int = 0,
    narrative_momentum_score: Decimal | None = None,
) -> SignalEvidence:
    """Combines already-computed per-domain signal strings into one "why
    now" evidence set (PRD S32). Each non-empty input category counts once
    toward `category_count`, regardless of how many individual signal
    strings it contributed -- evidence BREADTH (how many independent things
    are lining up), not raw signal volume, is what should move a token
    through the state bands.
    """
    reasons: list[str] = []
    category_count = 0

    if market_signals:
        reasons.extend(market_signals)
        category_count += 1
    if liquidity_signals:
        reasons.extend(liquidity_signals)
        category_count += 1
    if holder_signals:
        reasons.extend(holder_signals)
        category_count += 1
    if smart_money_entries > 0:
        reasons.append(f"{smart_money_entries} tracked smart-money wallet(s) entered")
        category_count += 1
    if (
        narrative_momentum_score is not None
        and narrative_momentum_score >= NARRATIVE_MOMENTUM_ACCELERATION_THRESHOLD
    ):
        reasons.append(f"Narrative momentum accelerating (momentum={narrative_momentum_score})")
        category_count += 1

    return SignalEvidence(reasons=reasons, category_count=category_count)


def classify_state(
    *,
    current_state: str,
    is_candidate: bool,
    hard_rejection: bool,
    evidence: SignalEvidence,
    opportunity_score: Decimal | None,
    previous_confirmed_opportunity_score: Decimal | None = None,
) -> str:
    """Returns the state this token's CURRENT evidence justifies.

    Never moves backward except into INVALIDATED from CONFIRMED/BREAKOUT
    (PRD S30/S33): a token that stops qualifying before ever reaching
    CONFIRMED simply holds at its last-reached state rather than an
    unspecified backward transition the PRD never defines.
    """
    if current_state in INVALIDATABLE_STATES:
        broke_down = (
            hard_rejection
            or not is_candidate
            or (
                previous_confirmed_opportunity_score is not None
                and opportunity_score is not None
                and (previous_confirmed_opportunity_score - opportunity_score) >= INVALIDATION_SCORE_DROP
            )
        )
        if broke_down:
            return AlertState.INVALIDATED
        if evidence.category_count >= BREAKOUT_MIN_EVIDENCE:
            return AlertState.BREAKOUT
        return AlertState.CONFIRMED

    if current_state == AlertState.INVALIDATED:
        return AlertState.INVALIDATED  # terminal for this lifecycle -- PRD draws no path back out

    if hard_rejection or not is_candidate:
        return current_state  # hold; no backward transition invented

    if evidence.category_count >= CONFIRMED_MIN_EVIDENCE:
        target = AlertState.CONFIRMED
    elif evidence.category_count >= DEVELOPING_MIN_EVIDENCE:
        target = AlertState.DEVELOPING
    else:
        target = AlertState.WATCHING

    current_rank = STATE_ORDER.index(current_state) if current_state in STATE_ORDER else 0
    target_rank = STATE_ORDER.index(target)
    return target if target_rank > current_rank else current_state


def should_alert(
    *,
    previous_state: str,
    new_state: str,
    last_alert_at: datetime | None,
    now: datetime,
    cooldown_minutes: int,
    is_priority: bool = False,
) -> bool:
    """Anti-spam gate (PRD S31, S33): alerts occur on state CHANGE only, and
    a token in cooldown after its last alert is suppressed unless the
    transition is one of PRD S33's named exceptions or an exceptional (S35)
    priority opportunity.
    """
    if new_state == previous_state:
        return False
    if last_alert_at is None or is_priority:
        return True
    if now - last_alert_at >= timedelta(minutes=cooldown_minutes):
        return True
    return (previous_state, new_state) in COOLDOWN_EXEMPT_TRANSITIONS


def is_priority_opportunity(
    *,
    opportunity_score: Decimal | None,
    risk_score: Decimal | None,
    narrative_momentum_score: Decimal | None,
    smart_money_entries: int,
) -> bool:
    """PRD S35's exceptional-opportunity override: Score > 95 AND major
    narrative acceleration AND strong smart-money activity AND low risk."""
    if opportunity_score is None or risk_score is None:
        return False
    return (
        opportunity_score > PRIORITY_MIN_OPPORTUNITY_SCORE
        and risk_score <= PRIORITY_MAX_RISK_SCORE
        and narrative_momentum_score is not None
        and narrative_momentum_score >= NARRATIVE_MOMENTUM_ACCELERATION_THRESHOLD
        and smart_money_entries > 0
    )


def is_top_ranked_candidate(*, token_id: int, ranked_token_ids: list[int]) -> bool:
    """PRD S22/S34: only the strongest candidate in a narrative should be
    alerted. `ranked_token_ids` must already be sorted strongest-first."""
    if not ranked_token_ids:
        return True  # no competition data available -- don't block on missing info
    return ranked_token_ids[0] == token_id


def is_under_alert_budget(*, alerts_in_last_hour: int, max_alerts_per_hour: int, is_priority: bool) -> bool:
    """PRD S35: configurable alerts/hour budget, overridable for exceptional
    opportunities."""
    if is_priority:
        return True
    return alerts_in_last_hour < max_alerts_per_hour

"""Cross-domain read aggregations for the dashboard (PRD S39 Overview).
Lives in `core` rather than any single domain app since it reads across
tokens/alerts/outcomes/configuration -- no one app owns "how is the whole
pipeline doing right now."
"""

from django.utils import timezone

from apps.alerts.models import Alert, AlertEvent, AlertState
from apps.configuration.services import config_to_dict, get_current_configuration
from apps.configuration.simulation import CandidateSnapshot, passes_configuration
from apps.holders.models import HolderSnapshot
from apps.liquidity.models import LiquiditySnapshot
from apps.market_data.models import TokenSnapshot
from apps.outcomes.models import TokenOutcome
from apps.tokens.models import Token
from apps.tokens.services import get_active_token_ids

_TRACKED_STATES = (
    AlertState.WATCHING,
    AlertState.DEVELOPING,
    AlertState.CONFIRMED,
    AlertState.BREAKOUT,
    AlertState.INVALIDATED,
)


def _latest_state_counts(token_ids: list[int]) -> dict[str, int]:
    """For each active token, its most recent AlertEvent.to_state -- a
    per-token lookup rather than a single grouped query, matching how
    apps/alerts/services.py already reads "current state" (there is no
    separate mutable current-state column, the event log is the source of
    truth). Fine at V1 token counts; would need a windowed query at scale.
    """
    counts = dict.fromkeys(_TRACKED_STATES, 0)
    for token_id in token_ids:
        latest = AlertEvent.objects.filter(token_id=token_id).order_by("-triggered_at").first()
        if latest and latest.to_state in counts:
            counts[latest.to_state] += 1
    return counts


def _candidate_count(token_ids: list[int], config: dict) -> int:
    count = 0
    for token_id in token_ids:
        token = Token.objects.get(pk=token_id)
        score = token.scores.order_by("-timestamp").first()
        if score is None:
            continue
        liquidity = LiquiditySnapshot.objects.filter(token_id=token_id).order_by("-timestamp").first()
        volume = TokenSnapshot.objects.filter(token_id=token_id).order_by("-timestamp").first()
        holders = HolderSnapshot.objects.filter(token_id=token_id).order_by("-timestamp").first()
        candidate = CandidateSnapshot(
            opportunity_score=score.opportunity_score,
            risk_score=score.risk_score,
            liquidity_usd=liquidity.liquidity_usd if liquidity else None,
            volume_5m_usd=volume.volume_5m if volume else None,
            holder_count=holders.holder_count if holders else None,
        )
        if passes_configuration(candidate, config):
            count += 1
    return count


def _hit_rate_pct(reached_count: int, total: int) -> float | None:
    """None (not 0%) when there's no outcome data yet -- a hit rate of 0%
    would misleadingly read as "we tried and failed," not "unmeasured."""
    if total == 0:
        return None
    return round(reached_count / total * 100, 1)


def get_overview_stats() -> dict:
    token_ids = get_active_token_ids()
    config = config_to_dict(get_current_configuration())
    state_counts = _latest_state_counts(token_ids)

    today = timezone.now().date()
    tokens_scanned_today = Token.objects.filter(created_at__date=today).count()

    total_outcomes = TokenOutcome.objects.count()
    reached_2x = TokenOutcome.objects.filter(reached_2x=True).count()
    reached_3x = TokenOutcome.objects.filter(reached_3x=True).count()

    return {
        "tokens_scanned_today": tokens_scanned_today,
        "candidates": _candidate_count(token_ids, config),
        "watchlist": state_counts[AlertState.WATCHING],
        "developing": state_counts[AlertState.DEVELOPING],
        "confirmed": state_counts[AlertState.CONFIRMED],
        "breakouts": state_counts[AlertState.BREAKOUT],
        "invalidated": state_counts[AlertState.INVALIDATED],
        "alerts_sent": Alert.objects.count(),
        "hit_rate_2x_pct": _hit_rate_pct(reached_2x, total_outcomes),
        "hit_rate_3x_pct": _hit_rate_pct(reached_3x, total_outcomes),
    }

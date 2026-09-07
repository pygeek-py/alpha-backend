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
from apps.scoring.models import TokenScore
from apps.tokens.models import Token
from apps.tokens.services import get_active_token_ids

_TRACKED_STATES = (
    AlertState.WATCHING,
    AlertState.DEVELOPING,
    AlertState.CONFIRMED,
    AlertState.BREAKOUT,
    AlertState.INVALIDATED,
)


def _latest_per_token(queryset, order_field: str, *value_fields) -> dict[int, tuple]:
    """One query total, not one per token_id: order by (token_id,
    -order_field) and keep only the first row seen per token_id in Python.
    Portable across SQLite (tests) and Postgres (prod) alike -- Postgres's
    `DISTINCT ON` isn't available on SQLite, and window-function-based
    "latest per group" queries need a subquery wrapper Django doesn't
    support cleanly in one step; this reduction is simple, correct, and
    identical on both backends at the row counts this project deals with.
    `queryset` must already be filtered to the token_ids of interest and
    must select a `token_id` field naturally (it does, by FK convention).
    `order_field` varies by model -- most snapshot models call it
    `timestamp`, AlertEvent calls it `triggered_at`.
    """
    latest: dict[int, tuple] = {}
    ordering = ("token_id", f"-{order_field}")
    for row in queryset.order_by(*ordering).values_list("token_id", *value_fields):
        token_id, values = row[0], row[1:]
        if token_id not in latest:
            latest[token_id] = values
    return latest


def _latest_state_counts(token_ids: list[int]) -> dict[str, int]:
    """For each active token, its most recent AlertEvent.to_state -- there
    is no separate mutable current-state column, the event log is the
    source of truth (matching how apps/alerts/services.py reads "current
    state"). One query for every token here (see _latest_per_token), not
    one per token -- this was originally a per-token loop and measured
    live to be the dominant cost behind the dashboard timing out entirely
    at real token counts (30+ tokens meant 30+ round trips here alone).
    """
    counts = dict.fromkeys(_TRACKED_STATES, 0)
    latest_states = _latest_per_token(
        AlertEvent.objects.filter(token_id__in=token_ids), "triggered_at", "to_state"
    )
    for (to_state,) in latest_states.values():
        if to_state in counts:
            counts[to_state] += 1
    return counts


def _candidate_count(token_ids: list[int], config: dict) -> int:
    """Same N+1 fix as _latest_state_counts, just wider: the original
    per-token loop issued 5 queries per token (a wasted Token.objects.get()
    that was never actually used beyond reaching its .scores related
    manager, plus one each for score/liquidity/volume/holders) -- roughly
    150+ round trips at 30 real active tokens, measured live as the single
    biggest contributor to /api/v1/dashboard/overview/ exceeding Vercel's
    9.5s server-side timeout. Now exactly 4 queries regardless of token
    count.
    """
    if not token_ids:
        return 0

    scores = _latest_per_token(
        TokenScore.objects.filter(token_id__in=token_ids), "timestamp", "opportunity_score", "risk_score"
    )
    liquidity = _latest_per_token(
        LiquiditySnapshot.objects.filter(token_id__in=token_ids), "timestamp", "liquidity_usd"
    )
    volume = _latest_per_token(TokenSnapshot.objects.filter(token_id__in=token_ids), "timestamp", "volume_5m")
    holders = _latest_per_token(
        HolderSnapshot.objects.filter(token_id__in=token_ids), "timestamp", "holder_count"
    )

    count = 0
    for token_id in token_ids:
        score_row = scores.get(token_id)
        if score_row is None:
            continue
        opportunity_score, risk_score = score_row
        liquidity_row = liquidity.get(token_id)
        volume_row = volume.get(token_id)
        holders_row = holders.get(token_id)
        candidate = CandidateSnapshot(
            opportunity_score=opportunity_score,
            risk_score=risk_score,
            liquidity_usd=liquidity_row[0] if liquidity_row else None,
            volume_5m_usd=volume_row[0] if volume_row else None,
            holder_count=holders_row[0] if holders_row else None,
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

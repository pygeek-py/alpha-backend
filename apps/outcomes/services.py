from django.utils import timezone

from apps.alerts.models import Alert
from apps.alerts.state_machine import BUDGET_GATED_STATES
from apps.holders.models import HolderSnapshot
from apps.liquidity.models import LiquiditySnapshot
from apps.market_data.models import TokenSnapshot
from apps.outcomes.models import TokenOutcome, TokenOutcomeSnapshot
from apps.outcomes.performance import (
    OutcomeRecord,
    age_bucket_for,
    compute_breakdown_by_age,
    compute_breakdown_by_narrative,
    compute_breakdown_by_score,
    compute_summary,
    score_bucket_for,
)
from apps.outcomes.tracking import (
    OFFSET_DELTAS,
    PricePoint,
    compute_due_offsets,
    compute_outcome_labels,
    compute_price_extremes,
    is_tracking_complete,
)

# Which alerts are meaningful enough to track outcomes for -- reuses the same
# "not just dashboard noise" set Batch 10's alert budget already established
# (PRD S57 measures alert quality as "Alerts sent -> Tokens reaching 2x", not
# every WATCHING candidate).
TRACKED_ALERT_STATES = BUDGET_GATED_STATES


def _nearest_at_or_before(queryset, token_id: int, at_time):
    return queryset.filter(token_id=token_id, timestamp__lte=at_time).order_by("-timestamp").first()


def create_missing_outcomes() -> list[TokenOutcome]:
    """Starts tracking for every meaningful alert that doesn't have a
    TokenOutcome yet. Anchored to Alert, not Prediction -- see
    apps/outcomes/models.py's TokenOutcome docstring. `alert.prediction` is
    backfilled onto the outcome when one exists (Batch 12) -- honestly None
    otherwise, same as before Batch 12 shipped."""
    alerts = Alert.objects.filter(state__in=TRACKED_ALERT_STATES, outcome__isnull=True)

    created = []
    for alert in alerts:
        initial_snapshot = _nearest_at_or_before(TokenSnapshot.objects, alert.token_id, alert.created_at)
        if initial_snapshot is None:
            continue  # nothing to anchor an initial price to yet -- retried next sweep
        outcome = TokenOutcome.objects.create(
            token=alert.token,
            alert=alert,
            prediction=alert.prediction,
            reference_timestamp=alert.created_at,
            initial_price=initial_snapshot.price,
            initial_market_cap=initial_snapshot.market_cap,
        )
        created.append(outcome)
    return created


def _price_points_up_to(outcome: TokenOutcome, at_time) -> list[PricePoint]:
    snapshots = TokenSnapshot.objects.filter(
        token_id=outcome.token_id,
        timestamp__gte=outcome.reference_timestamp,
        timestamp__lte=at_time,
    )
    return [PricePoint(timestamp=s.timestamp, price=s.price) for s in snapshots]


def _refresh_outcome_labels(outcome: TokenOutcome, *, now) -> None:
    all_points = _price_points_up_to(outcome, now)
    labels = compute_outcome_labels(
        initial_price=outcome.initial_price,
        reference_timestamp=outcome.reference_timestamp,
        price_points=all_points,
    )
    recorded_offsets = set(outcome.snapshots.values_list("offset_label", flat=True))

    outcome.max_multiple = labels.max_multiple
    outcome.max_drawdown_pct = labels.max_drawdown_pct
    outcome.reached_1_5x = labels.reached_1_5x
    outcome.reached_2x = labels.reached_2x
    outcome.reached_3x = labels.reached_3x
    outcome.reached_5x = labels.reached_5x
    outcome.reached_10x = labels.reached_10x
    outcome.time_to_2x = labels.time_to_2x
    outcome.time_to_3x = labels.time_to_3x
    outcome.time_to_5x = labels.time_to_5x
    outcome.tracking_complete = is_tracking_complete(recorded_offsets=recorded_offsets)
    outcome.last_outcome_at = now
    outcome.save()


def record_due_snapshots(outcome: TokenOutcome) -> list[TokenOutcomeSnapshot]:
    """Records any fixed offset (PRD S26) that has come due since the last
    sweep, then recomputes the outcome's all-time labels from the full price
    history so far."""
    now = timezone.now()
    already_recorded = set(outcome.snapshots.values_list("offset_label", flat=True))
    due_offsets = compute_due_offsets(
        reference_timestamp=outcome.reference_timestamp, now=now, already_recorded=already_recorded
    )
    if not due_offsets:
        return []

    created = []
    for label in due_offsets:
        due_at = outcome.reference_timestamp + OFFSET_DELTAS[label]
        recorded_at = min(due_at, now)  # never claim a future timestamp

        price_snapshot = _nearest_at_or_before(TokenSnapshot.objects, outcome.token_id, due_at)
        liquidity_snapshot = _nearest_at_or_before(LiquiditySnapshot.objects, outcome.token_id, due_at)
        holder_snapshot = _nearest_at_or_before(HolderSnapshot.objects, outcome.token_id, due_at)
        extremes = compute_price_extremes(
            initial_price=outcome.initial_price, price_points=_price_points_up_to(outcome, due_at)
        )

        created.append(
            TokenOutcomeSnapshot.objects.create(
                outcome=outcome,
                offset_label=label,
                recorded_at=recorded_at,
                price=price_snapshot.price if price_snapshot else None,
                market_cap=price_snapshot.market_cap if price_snapshot else None,
                liquidity_usd=liquidity_snapshot.liquidity_usd if liquidity_snapshot else None,
                volume_usd=price_snapshot.volume_5m if price_snapshot else None,
                holder_count=holder_snapshot.holder_count if holder_snapshot else None,
                max_gain_pct=extremes.max_gain_pct,
                max_drawdown_pct=extremes.max_drawdown_pct,
            )
        )

    _refresh_outcome_labels(outcome, now=now)
    return created


def sweep_due_outcomes() -> dict:
    """The periodic sweep (ARCHITECTURE.md S5): finds tokens/alerts whose
    next due offset has passed and records it, rather than scheduling one
    task per token per offset."""
    created_outcomes = create_missing_outcomes()

    total_snapshots = 0
    completed = 0
    for outcome in TokenOutcome.objects.filter(tracking_complete=False):
        was_complete_before = outcome.tracking_complete
        snapshots = record_due_snapshots(outcome)
        total_snapshots += len(snapshots)
        if outcome.tracking_complete and not was_complete_before:
            completed += 1

    return {
        "outcomes_started": len(created_outcomes),
        "snapshots_recorded": total_snapshots,
        "outcomes_completed": completed,
    }


def _top_narrative_name(token) -> str | None:
    links = list(token.narrative_links.all())
    if not links:
        return None
    top = max(links, key=lambda link: link.relevance_score or 0)
    return top.narrative.name


def _build_outcome_record(outcome: TokenOutcome) -> OutcomeRecord:
    reference_time = outcome.token.launched_at or outcome.token.created_at
    age_seconds = max((outcome.reference_timestamp - reference_time).total_seconds(), 0)

    return OutcomeRecord(
        reached_2x=outcome.reached_2x,
        reached_3x=outcome.reached_3x,
        reached_5x=outcome.reached_5x,
        max_multiple=outcome.max_multiple,
        time_to_2x_seconds=outcome.time_to_2x.total_seconds() if outcome.time_to_2x else None,
        time_to_3x_seconds=outcome.time_to_3x.total_seconds() if outcome.time_to_3x else None,
        tracking_complete=outcome.tracking_complete,
        narrative_name=_top_narrative_name(outcome.token),
        age_bucket=age_bucket_for(age_seconds),
        score_bucket=score_bucket_for(outcome.alert.score if outcome.alert else None),
    )


def get_performance_report() -> dict:
    """PRD S42 Historical Performance Dashboard. Breakdown scope is
    documented in apps/outcomes/performance.py's module docstring."""
    outcomes = TokenOutcome.objects.select_related("token", "alert").prefetch_related(
        "token__narrative_links__narrative"
    )
    records = [_build_outcome_record(outcome) for outcome in outcomes]

    return {
        "summary": compute_summary(records),
        "by_narrative": compute_breakdown_by_narrative(records),
        "by_age": compute_breakdown_by_age(records),
        "by_score": compute_breakdown_by_score(records),
    }

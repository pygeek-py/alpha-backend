import logging

from celery import shared_task

from apps.outcomes.services import sweep_due_outcomes

logger = logging.getLogger("alpha.outcomes")


@shared_task(name="outcomes.track_token_outcome")
def track_token_outcome() -> dict:
    """Single periodic sweep (ARCHITECTURE.md S5), not one task per token per
    offset: finds every (token, alert) pair whose next due offset has passed
    and records it, and starts tracking for any newly meaningful alert. This
    is simpler to reason about, restart-safe, and avoids scheduling storms
    when many tokens are alerted around the same time.
    """
    result = sweep_due_outcomes()
    if result["outcomes_started"] or result["snapshots_recorded"]:
        logger.info(
            "Outcome sweep: started=%s snapshots=%s completed=%s",
            result["outcomes_started"],
            result["snapshots_recorded"],
            result["outcomes_completed"],
        )
    return result

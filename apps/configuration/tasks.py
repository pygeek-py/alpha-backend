import logging

from celery import shared_task

from apps.configuration.services import maybe_auto_apply_ai_recommendation

logger = logging.getLogger("alpha.configuration")


@shared_task(name="configuration.evaluate_ai_configuration")
def evaluate_ai_configuration() -> dict:
    """Periodic check for the AI_AUTOMATIC autonomy mode. A no-op result is
    the expected, correct outcome whenever there isn't yet enough historical
    evidence to justify a change -- not a failure."""
    change = maybe_auto_apply_ai_recommendation()
    if change is None:
        return {"applied": False}

    logger.info("AI automatically adjusted configuration (change_id=%s): %s", change.id, change.reason)
    return {"applied": True, "change_id": change.id, "changed_fields": change.changed_fields}

import logging

from celery import shared_task

from apps.alerts.services import evaluate_alert_state
from apps.tokens.models import Token
from apps.tokens.services import get_active_token_ids

logger = logging.getLogger("alpha.alerts")


@shared_task(name="alerts.evaluate_alert_state", bind=True, max_retries=3, default_retry_delay=10)
def evaluate_alert_state_task(self, token_id: int) -> dict:
    try:
        token = Token.objects.get(pk=token_id)
        event = evaluate_alert_state(token)
    except Exception as exc:  # noqa: BLE001 - transient DB errors are retryable
        logger.warning("evaluate_alert_state failed for token_id=%s: %s", token_id, exc)
        raise self.retry(exc=exc) from exc

    if event is None:
        return {"transitioned": False}

    alert = event.alerts.first()
    if alert:
        logger.info("Token %s alert-worthy transition to %s", token.symbol, event.to_state)
    return {
        "transitioned": True,
        "from_state": event.from_state,
        "to_state": event.to_state,
        "alert_id": alert.id if alert else None,
    }


@shared_task(name="alerts.evaluate_alert_state_for_active_tokens")
def evaluate_alert_state_for_active_tokens() -> dict:
    token_ids = get_active_token_ids()
    for token_id in token_ids:
        evaluate_alert_state_task.delay(token_id)
    return {"queued": len(token_ids)}

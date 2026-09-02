import logging

from celery import shared_task

from apps.predictions.services import generate_prediction
from apps.tokens.models import Token
from apps.tokens.services import get_active_token_ids

logger = logging.getLogger("alpha.analysis")


@shared_task(name="predictions.generate_prediction", bind=True, max_retries=3, default_retry_delay=10)
def generate_prediction_task(self, token_id: int) -> dict:
    try:
        token = Token.objects.get(pk=token_id)
        result = generate_prediction(token)
    except Exception as exc:  # noqa: BLE001 - transient DB errors are retryable
        logger.warning("generate_prediction failed for token_id=%s: %s", token_id, exc)
        raise self.retry(exc=exc) from exc

    if result is None:
        return {"generated": False}
    return {
        "generated": True,
        "prediction_id": result.id,
        "probability_2x": str(result.probability_2x),
        "probability_3x": str(result.probability_3x),
        "probability_5x": str(result.probability_5x),
    }


@shared_task(name="predictions.generate_prediction_for_active_tokens")
def generate_prediction_for_active_tokens() -> dict:
    token_ids = get_active_token_ids()
    for token_id in token_ids:
        generate_prediction_task.delay(token_id)
    return {"queued": len(token_ids)}

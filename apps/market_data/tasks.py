import logging

from celery import shared_task

from apps.market_data.services import collect_market_data as _collect_market_data
from apps.tokens.models import Token
from apps.tokens.services import get_active_token_ids

logger = logging.getLogger("alpha.ingestion")


@shared_task(name="market_data.collect_market_data", bind=True, max_retries=3, default_retry_delay=10)
def collect_market_data(self, token_id: int) -> dict:
    try:
        token = Token.objects.get(pk=token_id)
        snapshot = _collect_market_data(token)
    except Exception as exc:  # noqa: BLE001 - provider/network errors are retryable
        logger.warning("collect_market_data failed for token_id=%s: %s", token_id, exc)
        raise self.retry(exc=exc) from exc
    return {"snapshot_id": snapshot.id}


@shared_task(name="market_data.collect_market_data_for_active_tokens")
def collect_market_data_for_active_tokens() -> dict:
    token_ids = get_active_token_ids()
    for token_id in token_ids:
        collect_market_data.delay(token_id)
    return {"queued": len(token_ids)}

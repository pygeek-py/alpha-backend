import logging

from celery import shared_task

from apps.tokens.services import discover_tokens as _discover_tokens

logger = logging.getLogger("alpha.ingestion")


@shared_task(name="tokens.discover_tokens")
def discover_tokens(limit: int = 50) -> dict:
    tokens = _discover_tokens(limit=limit)
    logger.info("discover_tokens: upserted %d tokens", len(tokens))
    return {"discovered": len(tokens)}

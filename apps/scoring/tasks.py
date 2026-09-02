import logging

from celery import shared_task

from apps.scoring.services import compute_and_persist_token_score, run_safety_analysis
from apps.tokens.models import Token
from apps.tokens.services import get_active_token_ids

logger = logging.getLogger("alpha.analysis")


@shared_task(name="scoring.analyze_token_safety", bind=True, max_retries=3, default_retry_delay=10)
def analyze_token_safety(self, token_id: int) -> dict:
    try:
        token = Token.objects.get(pk=token_id)
        result = run_safety_analysis(token)
    except Exception as exc:  # noqa: BLE001 - transient DB/provider errors are retryable
        logger.warning("analyze_token_safety failed for token_id=%s: %s", token_id, exc)
        raise self.retry(exc=exc) from exc

    if result.hard_rejection:
        logger.info("Token %s HARD REJECTED: %s", token.symbol, result.hard_rejection_reasons)
    return {"safety_check_id": result.id, "score": result.score, "hard_rejection": result.hard_rejection}


@shared_task(name="scoring.analyze_token_safety_for_active_tokens")
def analyze_token_safety_for_active_tokens() -> dict:
    token_ids = get_active_token_ids()
    for token_id in token_ids:
        analyze_token_safety.delay(token_id)
    return {"queued": len(token_ids)}


@shared_task(name="scoring.calculate_token_score", bind=True, max_retries=3, default_retry_delay=10)
def calculate_token_score(self, token_id: int) -> dict:
    try:
        token = Token.objects.get(pk=token_id)
        result = compute_and_persist_token_score(token)
    except Exception as exc:  # noqa: BLE001 - transient DB/provider errors are retryable
        logger.warning("calculate_token_score failed for token_id=%s: %s", token_id, exc)
        raise self.retry(exc=exc) from exc

    return {
        "token_score_id": result.id,
        "opportunity_score": str(result.opportunity_score),
        "risk_score": str(result.risk_score),
        "score_2x": str(result.score_2x),
        "score_3x": str(result.score_3x),
    }


@shared_task(name="scoring.calculate_token_score_for_active_tokens")
def calculate_token_score_for_active_tokens() -> dict:
    token_ids = get_active_token_ids()
    for token_id in token_ids:
        calculate_token_score.delay(token_id)
    return {"queued": len(token_ids)}

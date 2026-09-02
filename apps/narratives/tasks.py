import logging

from celery import shared_task

from apps.narratives.models import Narrative
from apps.narratives.services import detect_token_narratives, refresh_narrative_metrics
from apps.tokens.models import Token
from apps.tokens.services import get_active_token_ids

logger = logging.getLogger("alpha.analysis")


@shared_task(name="narratives.analyze_narrative", bind=True, max_retries=3, default_retry_delay=10)
def analyze_narrative(self, token_id: int) -> dict:
    try:
        token = Token.objects.get(pk=token_id)
        links = detect_token_narratives(token)
    except Exception as exc:  # noqa: BLE001 - transient DB errors are retryable
        logger.warning("analyze_narrative failed for token_id=%s: %s", token_id, exc)
        raise self.retry(exc=exc) from exc

    return {"narratives_matched": len(links)}


@shared_task(name="narratives.analyze_narrative_for_active_tokens")
def analyze_narrative_for_active_tokens() -> dict:
    token_ids = get_active_token_ids()
    for token_id in token_ids:
        analyze_narrative.delay(token_id)
    return {"queued": len(token_ids)}


@shared_task(name="narratives.refresh_narrative_metrics_for_active_narratives")
def refresh_narrative_metrics_for_active_narratives() -> dict:
    narrative_ids = list(Narrative.objects.filter(is_active=True).values_list("id", flat=True))
    for narrative_id in narrative_ids:
        narrative = Narrative.objects.get(pk=narrative_id)
        refresh_narrative_metrics(narrative)
    return {"refreshed": len(narrative_ids)}

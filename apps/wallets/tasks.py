import logging

from celery import shared_task

from apps.wallets.models import Wallet
from apps.wallets.services import classify_and_score_wallet, run_wallet_clustering

logger = logging.getLogger("alpha.analysis")


@shared_task(name="wallets.calculate_wallet_reputation", bind=True, max_retries=3, default_retry_delay=10)
def calculate_wallet_reputation(self, wallet_id: int) -> dict:
    try:
        wallet = Wallet.objects.get(pk=wallet_id)
        wallet, performance = classify_and_score_wallet(wallet)
    except Exception as exc:  # noqa: BLE001 - transient DB errors are retryable
        logger.warning("calculate_wallet_reputation failed for wallet_id=%s: %s", wallet_id, exc)
        raise self.retry(exc=exc) from exc

    return {
        "wallet_id": wallet.id,
        "classification": wallet.classification,
        "reputation_score": str(performance.reputation_score) if performance.reputation_score else None,
    }


@shared_task(name="wallets.calculate_wallet_reputation_for_active_wallets")
def calculate_wallet_reputation_for_active_wallets() -> dict:
    wallet_ids = list(
        Wallet.objects.filter(transactions__isnull=False).distinct().values_list("id", flat=True)
    )
    for wallet_id in wallet_ids:
        calculate_wallet_reputation.delay(wallet_id)
    return {"queued": len(wallet_ids)}


@shared_task(name="wallets.run_wallet_clustering")
def run_wallet_clustering_task() -> dict:
    clusters = run_wallet_clustering()
    return {"clusters_found": len(clusters)}

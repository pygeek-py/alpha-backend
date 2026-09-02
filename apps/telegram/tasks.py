import logging

from celery import shared_task

from apps.alerts.models import Alert
from apps.telegram.client import TelegramError
from apps.telegram.services import pending_alert_ids, send_alert_notification

logger = logging.getLogger("alpha.telegram")


@shared_task(name="telegram.send_telegram_alert", bind=True, max_retries=3, default_retry_delay=30)
def send_telegram_alert(self, alert_id: int) -> dict:
    try:
        alert = Alert.objects.get(pk=alert_id)
        sent = send_alert_notification(alert)
    except TelegramError as exc:
        logger.warning("send_telegram_alert failed for alert_id=%s: %s", alert_id, exc)
        raise self.retry(exc=exc) from exc
    return {"sent": sent}


@shared_task(name="telegram.send_pending_telegram_alerts")
def send_pending_telegram_alerts() -> dict:
    """Periodic sweep, not a direct trigger from apps/alerts on Alert
    creation -- keeps the two apps decoupled (matches apps/outcomes's
    sweep-based design) and means a delivery attempt is never lost just
    because Celery was briefly unavailable when the alert fired."""
    alert_ids = pending_alert_ids()
    for alert_id in alert_ids:
        send_telegram_alert.delay(alert_id)
    return {"queued": len(alert_ids)}

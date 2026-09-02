from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.alerts.models import Alert, AlertState
from apps.telegram.client import TelegramSendResult
from apps.telegram.models import TelegramConnection
from apps.telegram.tasks import send_pending_telegram_alerts, send_telegram_alert
from apps.tokens.factories import TokenFactory
from apps.users.factories import UserFactory


@pytest.mark.django_db
def test_send_telegram_alert_reports_not_sent_without_a_connection():
    alert = Alert.objects.create(token=TokenFactory(), state=AlertState.CONFIRMED, score=Decimal("80"))
    result = send_telegram_alert.delay(alert.id)
    assert result.get() == {"sent": False}


@pytest.mark.django_db
def test_send_telegram_alert_reports_sent_when_delivered():
    TelegramConnection.objects.create(user=UserFactory(), chat_id="123", notify_confirmed=True)
    alert = Alert.objects.create(token=TokenFactory(), state=AlertState.CONFIRMED, score=Decimal("80"))

    with patch("apps.telegram.services.TelegramClient") as mock_client:
        mock_client.return_value.send_message.return_value = TelegramSendResult(message_id=1)
        result = send_telegram_alert.delay(alert.id)
        payload = result.get()

    assert payload == {"sent": True}
    alert.refresh_from_db()
    assert alert.telegram_sent is True


@pytest.mark.django_db
def test_fan_out_queues_pending_alerts():
    TelegramConnection.objects.create(user=UserFactory(), chat_id="123", notify_confirmed=True)
    Alert.objects.create(token=TokenFactory(), state=AlertState.CONFIRMED, score=Decimal("80"))
    Alert.objects.create(token=TokenFactory(), state=AlertState.WATCHING, score=Decimal("60"))

    with patch("apps.telegram.services.TelegramClient") as mock_client:
        mock_client.return_value.send_message.return_value = TelegramSendResult(message_id=1)
        result = send_pending_telegram_alerts.delay()
        payload = result.get()

    # Only the CONFIRMED alert is a delivery candidate -- WATCHING is excluded.
    assert payload == {"queued": 1}

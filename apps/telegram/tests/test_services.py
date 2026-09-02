from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.alerts.models import Alert, AlertState
from apps.telegram.client import TelegramError, TelegramSendResult
from apps.telegram.models import TelegramConnection
from apps.telegram.services import (
    build_alert_message_context,
    get_active_connection,
    is_alert_eligible_for_delivery,
    pending_alert_ids,
    send_alert_notification,
    send_test_alert,
)
from apps.tokens.factories import TokenFactory
from apps.users.factories import UserFactory


def _connection(**overrides):
    user = overrides.pop("user", None) or UserFactory()
    defaults = {"chat_id": "12345"}
    defaults.update(overrides)
    return TelegramConnection.objects.create(user=user, **defaults)


def _alert(*, state=AlertState.CONFIRMED, is_priority=False, token=None):
    token = token or TokenFactory()
    return Alert.objects.create(token=token, state=state, score=Decimal("80"), is_priority=is_priority)


@pytest.mark.django_db
class TestGetActiveConnection:
    def test_none_when_no_connections_exist(self):
        assert get_active_connection() is None

    def test_returns_the_active_connection(self):
        conn = _connection()
        assert get_active_connection().id == conn.id

    def test_ignores_inactive_connections(self):
        _connection(is_active=False)
        assert get_active_connection() is None


@pytest.mark.django_db
class TestIsAlertEligibleForDelivery:
    def test_watching_is_never_eligible(self):
        conn = _connection(notify_watch=True)
        alert = _alert(state=AlertState.WATCHING)
        assert is_alert_eligible_for_delivery(alert, conn) is False

    def test_confirmed_follows_its_toggle(self):
        conn = _connection(notify_confirmed=False)
        alert = _alert(state=AlertState.CONFIRMED)
        assert is_alert_eligible_for_delivery(alert, conn) is False

    def test_confirmed_enabled_is_eligible(self):
        conn = _connection(notify_confirmed=True)
        alert = _alert(state=AlertState.CONFIRMED)
        assert is_alert_eligible_for_delivery(alert, conn) is True

    def test_priority_bypasses_the_state_toggle_when_priority_enabled(self):
        conn = _connection(notify_confirmed=False, notify_priority=True)
        alert = _alert(state=AlertState.CONFIRMED, is_priority=True)
        assert is_alert_eligible_for_delivery(alert, conn) is True

    def test_priority_alert_still_gated_by_notify_priority(self):
        conn = _connection(notify_confirmed=False, notify_priority=False)
        alert = _alert(state=AlertState.CONFIRMED, is_priority=True)
        assert is_alert_eligible_for_delivery(alert, conn) is False


@pytest.mark.django_db
class TestBuildAlertMessageContext:
    def test_gathers_context_from_the_token(self):
        alert = _alert()
        context = build_alert_message_context(alert)
        assert context.token_symbol == alert.token.symbol
        assert context.state == AlertState.CONFIRMED
        assert context.risk_score == alert.risk_score

    def test_missing_data_produces_none_fields(self):
        alert = _alert()
        context = build_alert_message_context(alert)
        assert context.market_cap is None
        assert context.liquidity_usd is None
        assert context.narrative_name == ""


@pytest.mark.django_db
class TestSendAlertNotification:
    def test_no_connection_returns_false(self):
        alert = _alert()
        assert send_alert_notification(alert) is False

    def test_ineligible_alert_returns_false_without_calling_telegram(self):
        _connection(notify_confirmed=False)
        alert = _alert(state=AlertState.CONFIRMED)
        with patch("apps.telegram.services.TelegramClient") as mock_client:
            assert send_alert_notification(alert) is False
            mock_client.assert_not_called()

    def test_eligible_alert_sends_and_marks_telegram_sent(self):
        _connection(notify_confirmed=True)
        alert = _alert(state=AlertState.CONFIRMED)
        with patch("apps.telegram.services.TelegramClient") as mock_client:
            mock_client.return_value.send_message.return_value = TelegramSendResult(message_id=1)
            result = send_alert_notification(alert)

        assert result is True
        alert.refresh_from_db()
        assert alert.telegram_sent is True
        assert alert.telegram_sent_at is not None

    def test_delivery_failure_propagates_and_does_not_mark_sent(self):
        _connection(notify_confirmed=True)
        alert = _alert(state=AlertState.CONFIRMED)
        with patch("apps.telegram.services.TelegramClient") as mock_client:
            mock_client.return_value.send_message.side_effect = TelegramError("boom")
            with pytest.raises(TelegramError):
                send_alert_notification(alert)

        alert.refresh_from_db()
        assert alert.telegram_sent is False


@pytest.mark.django_db
class TestPendingAlertIds:
    def test_excludes_already_sent_alerts(self):
        alert = _alert(state=AlertState.CONFIRMED)
        Alert.objects.filter(pk=alert.pk).update(telegram_sent=True)
        assert pending_alert_ids() == []

    def test_excludes_watching_alerts(self):
        _alert(state=AlertState.WATCHING)
        assert pending_alert_ids() == []

    def test_includes_recent_undelivered_alerts(self):
        alert = _alert(state=AlertState.CONFIRMED)
        assert pending_alert_ids() == [alert.id]

    def test_excludes_alerts_outside_the_delivery_window(self):
        alert = _alert(state=AlertState.CONFIRMED)
        Alert.objects.filter(pk=alert.pk).update(created_at=timezone.now() - timedelta(hours=3))
        assert pending_alert_ids() == []


@pytest.mark.django_db
class TestSendTestAlert:
    def test_success_updates_last_test_fields(self):
        conn = _connection()
        with patch("apps.telegram.services.TelegramClient") as mock_client:
            mock_client.return_value.send_message.return_value = TelegramSendResult(message_id=1)
            send_test_alert(conn)

        conn.refresh_from_db()
        assert conn.last_test_success is True
        assert conn.last_test_at is not None

    def test_failure_updates_last_test_fields_and_reraises(self):
        conn = _connection()
        with patch("apps.telegram.services.TelegramClient") as mock_client:
            mock_client.return_value.send_message.side_effect = TelegramError("boom")
            with pytest.raises(TelegramError):
                send_test_alert(conn)

        conn.refresh_from_db()
        assert conn.last_test_success is False

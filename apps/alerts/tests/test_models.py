from datetime import timedelta

import pytest
from django.utils import timezone

from apps.alerts.factories import AlertEventFactory, AlertFactory
from apps.alerts.models import Alert, AlertEvent, AlertState
from apps.tokens.factories import TokenFactory


@pytest.mark.django_db
class TestAlertEvent:
    def test_current_state_is_latest_event(self):
        """There's no mutable "current state" field on Token -- it's derived
        as the latest AlertEvent. This test is really documenting/protecting
        that design decision.

        Timestamps are explicit and spaced apart rather than two back-to-back
        timezone.now() calls -- those can land in the same microsecond and
        make ordering non-deterministic, which is exactly what caused this
        test to flake.
        """
        token = TokenFactory()
        now = timezone.now()
        AlertEventFactory(token=token, to_state=AlertState.DISCOVERED, triggered_at=now)
        AlertEventFactory(token=token, to_state=AlertState.WATCHING, triggered_at=now + timedelta(seconds=1))
        latest = AlertEvent.objects.filter(token=token).order_by("-triggered_at").first()
        assert latest.to_state == AlertState.WATCHING


@pytest.mark.django_db
class TestAlert:
    def test_create_linked_to_event(self):
        token = TokenFactory()
        event = AlertEventFactory(token=token, to_state=AlertState.CONFIRMED)
        alert = AlertFactory(
            token=token, alert_event=event, state=AlertState.CONFIRMED, reasons=["Volume acceleration"]
        )
        assert alert in token.alerts.all()
        assert alert.alert_event == event
        assert alert.telegram_sent is False

    def test_alert_event_deletion_nulls_out_not_cascades(self):
        alert = AlertFactory(alert_event=AlertEventFactory())
        alert.alert_event.delete()
        alert.refresh_from_db()
        assert alert.alert_event is None
        assert Alert.objects.filter(pk=alert.pk).exists()

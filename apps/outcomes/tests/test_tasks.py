from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.alerts.models import Alert, AlertState
from apps.market_data.models import TokenSnapshot
from apps.outcomes.models import TokenOutcome
from apps.outcomes.tasks import track_token_outcome
from apps.tokens.factories import TokenFactory


@pytest.mark.django_db
def test_task_reports_nothing_when_no_alerts_exist():
    result = track_token_outcome.delay()
    assert result.get() == {"outcomes_started": 0, "snapshots_recorded": 0, "outcomes_completed": 0}


@pytest.mark.django_db
def test_task_starts_tracking_for_a_confirmed_alert():
    token = TokenFactory()
    alert = Alert.objects.create(token=token, state=AlertState.CONFIRMED, score=Decimal("80"))
    TokenSnapshot.objects.create(token=token, timestamp=alert.created_at, price=Decimal("1.00"))

    result = track_token_outcome.delay()
    payload = result.get()

    assert payload["outcomes_started"] == 1
    assert TokenOutcome.objects.filter(alert=alert).exists()


@pytest.mark.django_db
def test_task_records_due_offsets_for_an_existing_outcome():
    token = TokenFactory()
    alert = Alert.objects.create(token=token, state=AlertState.CONFIRMED, score=Decimal("80"))
    past = timezone.now() - timedelta(minutes=6)
    TokenSnapshot.objects.create(token=token, timestamp=past, price=Decimal("1.00"))
    Alert.objects.filter(pk=alert.pk).update(created_at=past)

    result = track_token_outcome.delay()
    payload = result.get()

    assert payload["outcomes_started"] == 1
    assert payload["snapshots_recorded"] == 1

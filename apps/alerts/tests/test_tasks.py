from decimal import Decimal

import pytest
from django.utils import timezone

from apps.alerts.models import AlertEvent
from apps.alerts.tasks import evaluate_alert_state_for_active_tokens, evaluate_alert_state_task
from apps.holders.models import HolderSnapshot
from apps.liquidity.models import LiquiditySnapshot
from apps.market_data.models import TokenSnapshot
from apps.scoring.models import TokenScore
from apps.tokens.factories import TokenFactory


def _candidate_token():
    token = TokenFactory()
    now = timezone.now()
    TokenSnapshot.objects.create(
        token=token, timestamp=now, price=Decimal("0.001"), volume_5m=Decimal("10000")
    )
    LiquiditySnapshot.objects.create(token=token, timestamp=now, liquidity_usd=Decimal("50000"))
    HolderSnapshot.objects.create(token=token, timestamp=now, holder_count=200)
    TokenScore.objects.create(
        token=token,
        timestamp=now,
        opportunity_score=Decimal("60"),
        risk_score=Decimal("20"),
        score_2x=Decimal("60"),
        score_3x=Decimal("60"),
    )
    return token


@pytest.mark.django_db
def test_task_reports_no_transition_when_nothing_changed():
    token = TokenFactory()
    result = evaluate_alert_state_task.delay(token.id)
    assert result.get() == {"transitioned": False}


@pytest.mark.django_db
def test_task_reports_a_real_transition():
    token = _candidate_token()
    result = evaluate_alert_state_task.delay(token.id)
    payload = result.get()

    assert payload["transitioned"] is True
    assert payload["from_state"] == "discovered"
    assert payload["to_state"] == "watching"
    assert payload["alert_id"] is not None


@pytest.mark.django_db
def test_fan_out_queues_one_task_per_active_token():
    for _ in range(3):
        _candidate_token()
    TokenFactory(is_active=False)

    result = evaluate_alert_state_for_active_tokens.delay()

    assert result.get()["queued"] == 3
    assert AlertEvent.objects.count() == 3

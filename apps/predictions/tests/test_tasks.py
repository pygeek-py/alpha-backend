from decimal import Decimal

import pytest
from django.utils import timezone

from apps.predictions.models import Prediction
from apps.predictions.tasks import generate_prediction_for_active_tokens, generate_prediction_task
from apps.scoring.models import TokenScore
from apps.tokens.factories import TokenFactory


@pytest.mark.django_db
def test_task_reports_not_generated_when_no_score_exists():
    token = TokenFactory()
    result = generate_prediction_task.delay(token.id)
    assert result.get() == {"generated": False}


@pytest.mark.django_db
def test_task_reports_a_generated_prediction():
    token = TokenFactory()
    TokenScore.objects.create(
        token=token, timestamp=timezone.now(), opportunity_score=Decimal("65"),
        risk_score=Decimal("25"), score_2x=Decimal("70"), score_3x=Decimal("55"),
    )

    result = generate_prediction_task.delay(token.id)
    payload = result.get()

    assert payload["generated"] is True
    assert Prediction.objects.filter(id=payload["prediction_id"]).exists()


@pytest.mark.django_db
def test_fan_out_queues_one_task_per_active_token():
    for _ in range(3):
        token = TokenFactory()
        TokenScore.objects.create(
            token=token, timestamp=timezone.now(), opportunity_score=Decimal("65"),
            risk_score=Decimal("25"), score_2x=Decimal("70"), score_3x=Decimal("55"),
        )
    TokenFactory(is_active=False)

    result = generate_prediction_for_active_tokens.delay()

    assert result.get()["queued"] == 3
    assert Prediction.objects.count() == 3

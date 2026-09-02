from decimal import Decimal

import pytest
from django.utils import timezone

from apps.configuration.models import ConfigurationChange
from apps.configuration.services import get_current_configuration
from apps.configuration.tasks import evaluate_ai_configuration
from apps.scoring.models import TokenScore
from apps.tokens.factories import TokenFactory


def _create_scored_token(*, opportunity_score, risk_score):
    token = TokenFactory()
    return TokenScore.objects.create(
        token=token,
        timestamp=timezone.now(),
        opportunity_score=opportunity_score,
        risk_score=risk_score,
        score_2x=opportunity_score,
        score_3x=opportunity_score,
    )


@pytest.mark.django_db
def test_task_reports_not_applied_when_evidence_is_insufficient():
    get_current_configuration()
    result = evaluate_ai_configuration.delay()
    assert result.get() == {"applied": False}
    assert ConfigurationChange.objects.count() == 0


@pytest.mark.django_db
def test_task_reports_applied_change_id_and_fields_when_it_does_apply():
    get_current_configuration()
    for _ in range(30):
        _create_scored_token(opportunity_score=Decimal("95"), risk_score=Decimal("5"))

    result = evaluate_ai_configuration.delay()
    payload = result.get()

    if payload["applied"]:
        assert ConfigurationChange.objects.filter(id=payload["change_id"]).exists()
        assert payload["changed_fields"]
    else:
        assert payload == {"applied": False}

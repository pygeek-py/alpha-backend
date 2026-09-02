import pytest

from apps.scoring.models import TokenSafetyCheck, TokenScore
from apps.scoring.tasks import (
    analyze_token_safety,
    analyze_token_safety_for_active_tokens,
    calculate_token_score,
    calculate_token_score_for_active_tokens,
)
from apps.tokens.factories import TokenFactory


@pytest.mark.django_db
def test_analyze_token_safety_task_creates_a_check():
    token = TokenFactory()
    result = analyze_token_safety.delay(token.id)
    payload = result.get()
    assert TokenSafetyCheck.objects.filter(id=payload["safety_check_id"]).exists()


@pytest.mark.django_db
def test_analyze_token_safety_task_reports_hard_rejection():
    token = TokenFactory(mint_authority_revoked=False)
    result = analyze_token_safety.delay(token.id)
    assert result.get()["hard_rejection"] is True


@pytest.mark.django_db
def test_fan_out_queues_one_task_per_active_token():
    TokenFactory.create_batch(3)
    result = analyze_token_safety_for_active_tokens.delay()
    assert result.get()["queued"] == 3
    assert TokenSafetyCheck.objects.count() == 3


@pytest.mark.django_db
def test_calculate_token_score_task_creates_a_score():
    token = TokenFactory()
    result = calculate_token_score.delay(token.id)
    payload = result.get()
    assert TokenScore.objects.filter(id=payload["token_score_id"]).exists()


@pytest.mark.django_db
def test_calculate_token_score_fan_out_queues_all_active_tokens():
    TokenFactory.create_batch(3)
    TokenFactory(is_active=False)
    result = calculate_token_score_for_active_tokens.delay()
    assert result.get()["queued"] == 3
    assert TokenScore.objects.count() == 3

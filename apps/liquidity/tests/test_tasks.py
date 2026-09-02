import pytest

from apps.liquidity.models import LiquiditySnapshot
from apps.liquidity.tasks import collect_liquidity, collect_liquidity_for_active_tokens
from apps.tokens.factories import TokenFactory


@pytest.mark.django_db
def test_collect_liquidity_task_creates_snapshot():
    token = TokenFactory()
    result = collect_liquidity.delay(token.id)
    assert LiquiditySnapshot.objects.filter(id=result.get()["snapshot_id"]).exists()


@pytest.mark.django_db
def test_fan_out_queues_one_task_per_active_token():
    TokenFactory.create_batch(2)
    result = collect_liquidity_for_active_tokens.delay()
    assert result.get()["queued"] == 2
    assert LiquiditySnapshot.objects.count() == 2

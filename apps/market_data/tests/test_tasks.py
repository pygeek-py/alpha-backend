import pytest

from apps.market_data.models import TokenSnapshot
from apps.market_data.tasks import collect_market_data, collect_market_data_for_active_tokens
from apps.tokens.factories import TokenFactory


@pytest.mark.django_db
def test_collect_market_data_task_creates_snapshot():
    token = TokenFactory()
    result = collect_market_data.delay(token.id)
    assert TokenSnapshot.objects.filter(id=result.get()["snapshot_id"]).exists()


@pytest.mark.django_db
def test_fan_out_queues_one_task_per_active_token():
    TokenFactory.create_batch(3)
    result = collect_market_data_for_active_tokens.delay()
    assert result.get()["queued"] == 3
    # With CELERY_TASK_ALWAYS_EAGER, .delay() inside the fan-out task also
    # runs synchronously, so all 3 snapshots should already exist.
    assert TokenSnapshot.objects.count() == 3

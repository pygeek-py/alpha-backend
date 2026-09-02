import pytest

from apps.holders.models import HolderSnapshot
from apps.holders.tasks import collect_holders, collect_holders_for_active_tokens
from apps.tokens.factories import TokenFactory


@pytest.mark.django_db
def test_collect_holders_task_creates_snapshot():
    token = TokenFactory()
    result = collect_holders.delay(token.id)
    assert HolderSnapshot.objects.filter(id=result.get()["snapshot_id"]).exists()


@pytest.mark.django_db
def test_fan_out_queues_one_task_per_active_token():
    TokenFactory.create_batch(2)
    result = collect_holders_for_active_tokens.delay()
    assert result.get()["queued"] == 2
    assert HolderSnapshot.objects.count() == 2

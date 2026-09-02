import pytest
from django.utils import timezone

from apps.holders.models import HolderSnapshot
from apps.tokens.factories import TokenFactory


@pytest.mark.django_db
class TestHolderSnapshot:
    def test_create_and_relate(self):
        token = TokenFactory()
        snapshot = HolderSnapshot.objects.create(
            token=token, timestamp=timezone.now(), holder_count=412, top_holder_pct="8.50"
        )
        assert token.holder_snapshots.get() == snapshot

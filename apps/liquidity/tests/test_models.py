import pytest
from django.utils import timezone

from apps.liquidity.models import LiquiditySnapshot
from apps.tokens.factories import TokenFactory


@pytest.mark.django_db
class TestLiquiditySnapshot:
    def test_create_and_relate(self):
        token = TokenFactory()
        snapshot = LiquiditySnapshot.objects.create(
            token=token, timestamp=timezone.now(), liquidity_usd="75000.50", lp_locked=True
        )
        assert token.liquidity_snapshots.get() == snapshot
        assert snapshot.lp_burned is None

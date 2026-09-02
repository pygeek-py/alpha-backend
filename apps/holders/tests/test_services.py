from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.holders.models import HolderSnapshot
from apps.holders.services import collect_holders, get_holder_features
from apps.tokens.factories import TokenFactory


@pytest.mark.django_db
class TestCollectHolders:
    def test_creates_snapshot_linked_to_token(self):
        token = TokenFactory()
        snapshot = collect_holders(token)
        assert snapshot.token == token
        assert snapshot.holder_count >= 1
        assert token.holder_snapshots.count() == 1


@pytest.mark.django_db
class TestGetHolderFeatures:
    def test_no_snapshots_returns_none(self):
        token = TokenFactory()
        assert get_holder_features(token) is None

    def test_uses_up_to_three_most_recent_snapshots(self):
        token = TokenFactory()
        now = timezone.now()
        HolderSnapshot.objects.create(token=token, timestamp=now, holder_count=100)
        HolderSnapshot.objects.create(
            token=token, timestamp=now + timedelta(minutes=5), holder_count=200
        )
        HolderSnapshot.objects.create(
            token=token, timestamp=now + timedelta(minutes=10), holder_count=600
        )

        features = get_holder_features(token)

        assert features.holder_growth_count == 400  # 600 - 200 (latest vs previous)
        assert features.holder_growth_acceleration == Decimal("2.0000")

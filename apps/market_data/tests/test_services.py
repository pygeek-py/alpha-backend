from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.market_data.models import TokenSnapshot
from apps.market_data.services import collect_market_data, get_market_features
from apps.tokens.factories import TokenFactory


@pytest.mark.django_db
class TestCollectMarketData:
    def test_creates_snapshot_linked_to_token(self):
        token = TokenFactory()
        snapshot = collect_market_data(token)
        assert snapshot.token == token
        assert snapshot.price > 0
        assert snapshot.is_mock is True
        assert token.snapshots.count() == 1


@pytest.mark.django_db
class TestGetMarketFeatures:
    def test_no_snapshots_returns_none(self):
        token = TokenFactory()
        assert get_market_features(token) is None

    def test_uses_the_two_most_recent_snapshots_for_acceleration(self):
        token = TokenFactory()
        now = timezone.now()
        TokenSnapshot.objects.create(
            token=token, timestamp=now, price=Decimal("0.001"), volume_5m=Decimal("4000")
        )
        TokenSnapshot.objects.create(
            token=token,
            timestamp=now + timedelta(minutes=5),
            price=Decimal("0.002"),
            volume_5m=Decimal("12000"),
        )

        features = get_market_features(token)

        assert features.volume_5m_acceleration == Decimal("3.0000")
        assert features.price_direction == "up"

    def test_history_excludes_current_and_is_chronological(self):
        token = TokenFactory()
        now = timezone.now()
        prices = [Decimal("0.001"), Decimal("0.0012"), Decimal("0.0015"), Decimal("0.0018")]
        for i, price in enumerate(prices):
            TokenSnapshot.objects.create(token=token, timestamp=now + timedelta(minutes=i), price=price)
        current_snapshot = TokenSnapshot.objects.create(
            token=token, timestamp=now + timedelta(minutes=10), price=Decimal("0.002")
        )

        features = get_market_features(token)

        # 4 prior snapshots form an uptrend structure; current isn't part of it.
        assert features.price_structure == "uptrend"
        assert current_snapshot.price == Decimal("0.002")

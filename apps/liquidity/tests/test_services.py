from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.liquidity.models import LiquiditySnapshot
from apps.liquidity.services import collect_liquidity, get_liquidity_features
from apps.market_data.models import TokenSnapshot
from apps.tokens.factories import TokenFactory


@pytest.mark.django_db
class TestCollectLiquidity:
    def test_creates_snapshot_linked_to_token(self):
        token = TokenFactory()
        snapshot = collect_liquidity(token)
        assert snapshot.token == token
        assert snapshot.liquidity_usd > 0
        assert token.liquidity_snapshots.count() == 1


@pytest.mark.django_db
class TestGetLiquidityFeatures:
    def test_no_snapshots_returns_none(self):
        token = TokenFactory()
        assert get_liquidity_features(token) is None

    def test_pulls_market_cap_and_volume_from_latest_token_snapshot(self):
        token = TokenFactory()
        now = timezone.now()
        LiquiditySnapshot.objects.create(token=token, timestamp=now, liquidity_usd=Decimal("50000"))
        TokenSnapshot.objects.create(
            token=token,
            timestamp=now,
            price=Decimal("0.001"),
            market_cap=Decimal("500000"),
            volume_5m=Decimal("25000"),
        )

        features = get_liquidity_features(token)

        assert features.liquidity_mcap_ratio_pct == Decimal("10.00")
        assert features.volume_liquidity_ratio == Decimal("0.5000")

    def test_uses_the_two_most_recent_liquidity_snapshots(self):
        token = TokenFactory()
        now = timezone.now()
        LiquiditySnapshot.objects.create(token=token, timestamp=now, liquidity_usd=Decimal("50000"))
        LiquiditySnapshot.objects.create(
            token=token, timestamp=now + timedelta(minutes=5), liquidity_usd=Decimal("90000")
        )

        features = get_liquidity_features(token)

        assert features.liquidity_change_pct == Decimal("80.00")

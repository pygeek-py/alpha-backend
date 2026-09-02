import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.market_data.models import TokenSnapshot
from apps.tokens.factories import TokenFactory


@pytest.mark.django_db
class TestTokenSnapshot:
    def test_create(self):
        token = TokenFactory()
        snapshot = TokenSnapshot.objects.create(
            token=token, timestamp=timezone.now(), price="0.000001234", market_cap="50000.00"
        )
        assert snapshot.token == token
        assert snapshot.is_mock is False  # SourcedModel default, not TokenFactory's override

    def test_unique_per_token_timestamp_source(self):
        token = TokenFactory()
        now = timezone.now()
        TokenSnapshot.objects.create(token=token, timestamp=now, price="1", source="mock")
        with pytest.raises(IntegrityError):
            TokenSnapshot.objects.create(token=token, timestamp=now, price="2", source="mock")

    def test_related_name_from_token(self):
        token = TokenFactory()
        TokenSnapshot.objects.create(token=token, timestamp=timezone.now(), price="1")
        assert token.snapshots.count() == 1

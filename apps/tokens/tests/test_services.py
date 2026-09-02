import pytest

from apps.tokens.models import Token
from apps.tokens.services import discover_tokens, get_active_token_ids


@pytest.mark.django_db
class TestDiscoverTokens:
    def test_creates_tokens(self):
        tokens = discover_tokens(limit=5)
        assert len(tokens) == 5
        assert Token.objects.count() == 5

    def test_created_tokens_are_labeled_mock(self):
        tokens = discover_tokens(limit=1)
        assert tokens[0].is_mock is True
        assert tokens[0].source == "mock"

    def test_rediscovering_same_token_updates_not_duplicates(self):
        # The mock provider is deterministic within a time bucket, so calling
        # it twice in quick succession should upsert the same rows, not
        # create duplicates -- this is what proves address is the natural key.
        discover_tokens(limit=5)
        count_after_first = Token.objects.count()
        discover_tokens(limit=5)
        assert Token.objects.count() == count_after_first


@pytest.mark.django_db
class TestGetActiveTokenIds:
    def test_only_returns_active_tokens(self):
        discover_tokens(limit=3)
        inactive = Token.objects.first()
        inactive.is_active = False
        inactive.save()

        active_ids = get_active_token_ids()
        assert inactive.id not in active_ids
        assert len(active_ids) == 2

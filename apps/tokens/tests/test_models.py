import pytest
from django.db import IntegrityError

from apps.tokens.factories import TokenFactory
from apps.tokens.models import Token


@pytest.mark.django_db
class TestToken:
    def test_create_with_defaults(self):
        token = TokenFactory()
        assert token.is_active is True
        assert token.decimals == 9
        assert token.mint_authority_revoked is None

    def test_address_is_unique(self):
        TokenFactory(address="Mint111")
        with pytest.raises(IntegrityError):
            TokenFactory(address="Mint111")

    def test_str_prefers_symbol(self):
        token = TokenFactory(symbol="DOGE", address="Mint222")
        assert str(token) == "DOGE"

    def test_str_falls_back_to_address_prefix(self):
        token = Token.objects.create(address="AbCdEfGh12345678", symbol="")
        assert str(token) == "AbCdEfGh"

    def test_is_mock_defaults_true_via_factory(self):
        token = TokenFactory()
        assert token.is_mock is True
        assert token.source == "mock"

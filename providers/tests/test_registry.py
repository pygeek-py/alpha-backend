import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from providers.hybrid import HybridSolanaProvider
from providers.mock import MockMarketDataProvider, MockSolanaProvider, MockWalletDataProvider
from providers.registry import get_chain_provider, get_market_data_provider, get_wallet_data_provider


class TestRegistry:
    def test_default_settings_resolve_to_mock(self):
        assert isinstance(get_chain_provider(), MockSolanaProvider)
        assert isinstance(get_market_data_provider(), MockMarketDataProvider)
        assert isinstance(get_wallet_data_provider(), MockWalletDataProvider)

    def test_unknown_provider_name_fails_loudly(self):
        get_chain_provider.cache_clear()
        try:
            with override_settings(SOLANA_CHAIN_DATA_PROVIDER="not_a_real_provider"):
                with pytest.raises(ImproperlyConfigured, match="not_a_real_provider"):
                    get_chain_provider()
        finally:
            get_chain_provider.cache_clear()

    def test_birdeye_quicknode_key_resolves_to_hybrid_provider(self):
        get_chain_provider.cache_clear()
        try:
            with override_settings(
                SOLANA_CHAIN_DATA_PROVIDER="birdeye_quicknode",
                BIRDEYE_API_KEY="fake-key",
                QUICKNODE_RPC_URL="https://fake.example/token",
            ):
                assert isinstance(get_chain_provider(), HybridSolanaProvider)
        finally:
            get_chain_provider.cache_clear()

from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from django.core.cache import cache
from django.test import override_settings

from providers.birdeye import BirdeyeClient, BirdeyeMarketDataProvider, BirdeyeSolanaProvider
from providers.exceptions import ProviderError


@pytest.fixture(autouse=True)
def _clear_cache():
    """LocMemCache (test settings) persists across tests in the same run --
    without this, an earlier test's cached Birdeye response leaks into a
    later test that expects a fresh call."""
    cache.clear()
    yield
    cache.clear()

BONK = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"

# Trimmed fixtures mirroring the real shape observed from Birdeye's live API
# during development (see providers/birdeye.py's module docstring).
OVERVIEW_RESPONSE = {
    "success": True,
    "data": {
        "price": 0.0000030029,
        "marketCap": 264183159.58,
        "liquidity": 2916657.10,
        "holder": 1009262,
        "totalSupply": 87994537958263.66,
        "v1mUSD": 1041.98,
        "v5mUSD": 1670.11,
        "v1hUSD": 50000.0,
        "vBuy5mUSD": 770.56,
        "vSell5mUSD": 899.55,
    },
}
NEW_LISTING_RESPONSE = {
    "success": True,
    "data": {
        "items": [
            {
                "address": "SomeMint111",
                "symbol": "TEST",
                "name": "Test Token",
                "decimals": 6,
                "source": "pump_amm",
                "liquidityAddedAt": "2026-08-31T22:29:35",
                "liquidity": 17970.65,
            }
        ]
    },
}
HOLDER_LIST_RESPONSE = {
    "success": True,
    "data": {
        "items": [
            {"ui_amount": 7193508364031.432},
            {"ui_amount": 5772593511837.953},
        ]
    },
}


def _mock_response(payload: dict, status: int = 200) -> Mock:
    response = Mock()
    response.status_code = status
    response.json.return_value = payload
    response.text = str(payload)
    return response


class TestBirdeyeClient:
    def test_requires_api_key(self):
        with override_settings(BIRDEYE_API_KEY=""):
            with pytest.raises(ProviderError, match="not configured"):
                BirdeyeClient()

    @patch("providers.birdeye.requests.get")
    def test_raises_on_non_200(self, mock_get):
        mock_get.return_value = _mock_response({"success": False, "message": "nope"}, status=500)
        client = BirdeyeClient(api_key="fake-key")
        with pytest.raises(ProviderError, match="500"):
            client.get_json("/defi/token_overview")

    @patch("providers.birdeye.requests.get")
    def test_raises_when_success_is_false(self, mock_get):
        mock_get.return_value = _mock_response({"success": False, "message": "rate limited"})
        client = BirdeyeClient(api_key="fake-key")
        with pytest.raises(ProviderError, match="rate limited"):
            client.get_json("/defi/token_overview")

    @patch("providers.birdeye.requests.get")
    def test_caches_when_cache_seconds_given(self, mock_get):
        mock_get.return_value = _mock_response(OVERVIEW_RESPONSE)
        client = BirdeyeClient(api_key="fake-key")
        client.get_json("/defi/token_overview", {"address": BONK}, cache_seconds=30)
        client.get_json("/defi/token_overview", {"address": BONK}, cache_seconds=30)
        assert mock_get.call_count == 1


class TestBirdeyeMarketDataProvider:
    @patch("providers.birdeye.requests.get")
    def test_get_market_snapshot_maps_real_field_names(self, mock_get):
        mock_get.return_value = _mock_response(OVERVIEW_RESPONSE)
        provider = BirdeyeMarketDataProvider(client=BirdeyeClient(api_key="fake-key"))
        snapshot = provider.get_market_snapshot(BONK)

        assert snapshot.price == Decimal("0.0000030029")
        assert snapshot.volume_5m == Decimal("1670.11")
        assert snapshot.buy_volume_5m + snapshot.sell_volume_5m == snapshot.volume_5m
        assert snapshot.volume_15m is None  # Birdeye has no native 15m bucket
        assert snapshot.is_mock is False
        assert snapshot.source == "birdeye"

    @patch("providers.birdeye.requests.get")
    def test_get_liquidity_snapshot(self, mock_get):
        mock_get.return_value = _mock_response(OVERVIEW_RESPONSE)
        provider = BirdeyeMarketDataProvider(client=BirdeyeClient(api_key="fake-key"))
        snapshot = provider.get_liquidity_snapshot(BONK)

        assert snapshot.liquidity_usd == Decimal("2916657.10")
        assert snapshot.lp_locked is None  # needs token_security, not on this tier


class TestBirdeyeSolanaProvider:
    @patch("providers.birdeye.requests.get")
    def test_discover_tokens_maps_new_listing_items(self, mock_get):
        mock_get.return_value = _mock_response(NEW_LISTING_RESPONSE)
        provider = BirdeyeSolanaProvider(client=BirdeyeClient(api_key="fake-key"))
        tokens = provider.discover_tokens(limit=10)

        assert len(tokens) == 1
        assert tokens[0].address == "SomeMint111"
        assert tokens[0].symbol == "TEST"
        assert tokens[0].mint_authority_revoked is None  # needs token_security

    @patch("providers.birdeye.requests.get")
    def test_get_holder_distribution_computes_percentages_from_supply(self, mock_get):
        mock_get.side_effect = [
            _mock_response(OVERVIEW_RESPONSE),
            _mock_response(HOLDER_LIST_RESPONSE),
        ]
        provider = BirdeyeSolanaProvider(client=BirdeyeClient(api_key="fake-key"))
        dist = provider.get_holder_distribution(BONK)

        assert dist.holder_count == 1009262
        # top_holder_pct = 7193508364031.432 / 87994537958263.66 * 100
        assert dist.top_holder_pct == Decimal("8.17")
        assert dist.creator_pct is None  # not identifiable from this endpoint


class TestRegistrySwapToBirdeye:
    def test_switching_setting_resolves_to_birdeye(self):
        from providers.registry import get_market_data_provider

        get_market_data_provider.cache_clear()
        try:
            with override_settings(SOLANA_MARKET_DATA_PROVIDER="birdeye", BIRDEYE_API_KEY="fake-key"):
                provider = get_market_data_provider()
                assert isinstance(provider, BirdeyeMarketDataProvider)
        finally:
            get_market_data_provider.cache_clear()

    def test_missing_key_fails_loudly_at_instantiation(self):
        """Unlike an unknown provider *name* (ImproperlyConfigured, raised by
        the registry itself), a configured-but-empty API key is a
        provider-level concern -- it surfaces as ProviderError from
        BirdeyeClient's own constructor."""
        from providers.registry import get_market_data_provider

        get_market_data_provider.cache_clear()
        try:
            with override_settings(SOLANA_MARKET_DATA_PROVIDER="birdeye", BIRDEYE_API_KEY=""):
                with pytest.raises(ProviderError, match="not configured"):
                    get_market_data_provider()
        finally:
            get_market_data_provider.cache_clear()

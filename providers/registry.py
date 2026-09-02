"""Resolves the configured provider implementation from Django settings, so
swapping vendors is a config change, not a code change in any app that
consumes a provider. Unknown provider keys fail loudly at call time rather
than silently falling back to mock -- a misconfigured provider name in
production should never be mistaken for mock data.
"""

from functools import lru_cache

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from providers.birdeye import BirdeyeMarketDataProvider, BirdeyeSolanaProvider
from providers.hybrid import HybridSolanaProvider
from providers.interfaces import (
    MarketDataProvider,
    NullSocialDataProvider,
    SocialDataProvider,
    SolanaDataProvider,
    WalletDataProvider,
)
from providers.mock import (
    MockMarketDataProvider,
    MockSocialDataProvider,
    MockSolanaProvider,
    MockWalletDataProvider,
)

_CHAIN_PROVIDERS: dict[str, type[SolanaDataProvider]] = {
    "mock": MockSolanaProvider,
    "birdeye": BirdeyeSolanaProvider,
    "birdeye_quicknode": HybridSolanaProvider,
}
_MARKET_PROVIDERS: dict[str, type[MarketDataProvider]] = {
    "mock": MockMarketDataProvider,
    "birdeye": BirdeyeMarketDataProvider,
}
_WALLET_PROVIDERS: dict[str, type[WalletDataProvider]] = {
    "mock": MockWalletDataProvider,
}
_SOCIAL_PROVIDERS: dict[str, type[SocialDataProvider]] = {
    "none": NullSocialDataProvider,
    "mock": MockSocialDataProvider,
}


def _resolve(registry: dict[str, type], key: str, setting_name: str):
    try:
        provider_class = registry[key]
    except KeyError as exc:
        available = ", ".join(sorted(registry))
        raise ImproperlyConfigured(
            f"{setting_name}={key!r} is not a registered provider. Available: {available}."
        ) from exc
    return provider_class()


@lru_cache(maxsize=1)
def get_chain_provider() -> SolanaDataProvider:
    return _resolve(_CHAIN_PROVIDERS, settings.SOLANA_CHAIN_DATA_PROVIDER, "SOLANA_CHAIN_DATA_PROVIDER")


@lru_cache(maxsize=1)
def get_market_data_provider() -> MarketDataProvider:
    return _resolve(_MARKET_PROVIDERS, settings.SOLANA_MARKET_DATA_PROVIDER, "SOLANA_MARKET_DATA_PROVIDER")


@lru_cache(maxsize=1)
def get_wallet_data_provider() -> WalletDataProvider:
    return _resolve(_WALLET_PROVIDERS, settings.SOLANA_WALLET_DATA_PROVIDER, "SOLANA_WALLET_DATA_PROVIDER")


@lru_cache(maxsize=1)
def get_social_data_provider() -> SocialDataProvider:
    return _resolve(_SOCIAL_PROVIDERS, settings.SOCIAL_DATA_PROVIDER, "SOCIAL_DATA_PROVIDER")

"""Provider interfaces (PRD S7, S11 "the application should not tightly
couple itself to a single external data provider"). Business logic in
apps/*/services.py depends only on these ABCs, resolved through
providers/registry.py -- never on a concrete provider class directly.
"""

from abc import ABC, abstractmethod
from datetime import datetime

from providers.types import (
    DiscoveredToken,
    HolderDistribution,
    LiquiditySnapshotData,
    MarketSnapshotData,
    NarrativeSignal,
    WalletTransactionData,
)


class SolanaDataProvider(ABC):
    """On-chain token identity and holder-distribution facts -- discovery,
    mint/freeze authority, ownership, holder concentration. Not financial/
    market data (that's MarketDataProvider)."""

    @abstractmethod
    def discover_tokens(self, *, limit: int = 50, since: datetime | None = None) -> list[DiscoveredToken]:
        """Newly created/actively trending tokens worth tracking."""

    @abstractmethod
    def get_holder_distribution(self, token_address: str) -> HolderDistribution:
        """Current holder count and concentration for a token."""


class MarketDataProvider(ABC):
    """Price, market cap, volume, and liquidity for a token."""

    @abstractmethod
    def get_market_snapshot(self, token_address: str) -> MarketSnapshotData:
        """Current price/market-cap/volume state."""

    @abstractmethod
    def get_liquidity_snapshot(self, token_address: str) -> LiquiditySnapshotData:
        """Current primary-pool liquidity state."""


class WalletDataProvider(ABC):
    """Per-wallet transaction history for a token."""

    @abstractmethod
    def get_recent_transactions(
        self, token_address: str, *, limit: int = 50, since: datetime | None = None
    ) -> list[WalletTransactionData]:
        """Recent buy/sell transactions involving this token."""


class SocialDataProvider(ABC):
    """Social attention/mention data (PRD S20) -- the explicit extension
    point for adding a real social provider later without restructuring the
    narrative engine (ARCHITECTURE.md S10: on-chain-only for V1, no paid
    X/Twitter integration yet). apps/narratives/scoring.py works correctly
    whether or not a real implementation is configured.
    """

    @abstractmethod
    def get_mention_signal(self, query: str) -> NarrativeSignal | None:
        """Mention volume for `query` (e.g. a narrative name or keyword).
        None means no signal available -- callers must treat that as "no
        data," never as "zero mentions."
        """


class NullSocialDataProvider(SocialDataProvider):
    """Always returns None. This -- not the mock -- is the default
    SOCIAL_DATA_PROVIDER, deliberately: narrative strength/momentum get
    persisted and consumed by later scoring/prediction batches, so silently
    blending in *simulated* mention numbers by default would contaminate an
    otherwise real, on-chain-only pipeline with fabricated data (exactly
    what the project's mock/real separation rule exists to prevent).
    MockSocialDataProvider stays registered for anyone who explicitly wants
    to exercise the blending code path in local dev/tests.
    """

    def get_mention_signal(self, query: str) -> NarrativeSignal | None:
        return None

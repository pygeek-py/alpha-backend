"""Plain data contracts returned by every provider implementation. Deliberately
NOT Django model instances -- the provider layer must stay usable and testable
without a database or Django app registry, per ARCHITECTURE.md S7. The service
layer (apps/*/services.py) is what converts these into ORM writes.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class DiscoveredToken:
    address: str
    symbol: str
    name: str
    decimals: int
    creator_address: str
    launched_at: datetime
    mint_authority_revoked: bool | None
    freeze_authority_revoked: bool | None
    is_mutable_metadata: bool | None
    top_holder_pct_at_launch: Decimal | None
    is_mock: bool
    source: str


@dataclass(frozen=True)
class HolderDistribution:
    token_address: str
    timestamp: datetime
    holder_count: int
    top_holder_pct: Decimal | None
    top5_pct: Decimal | None
    top10_pct: Decimal | None
    creator_pct: Decimal | None
    insider_pct: Decimal | None
    is_mock: bool
    source: str


@dataclass(frozen=True)
class MarketSnapshotData:
    token_address: str
    timestamp: datetime
    price: Decimal
    market_cap: Decimal | None
    volume_1m: Decimal | None
    volume_5m: Decimal | None
    volume_15m: Decimal | None
    volume_1h: Decimal | None
    buy_volume_5m: Decimal | None
    sell_volume_5m: Decimal | None
    unique_buyers_5m: int | None
    unique_sellers_5m: int | None
    is_mock: bool
    source: str
    # Identity metadata (PRD S21), captured incidentally when the same API
    # response happens to include it -- see Token.description's docstring.
    description: str = ""
    website: str = ""
    social_links: dict = field(default_factory=dict)


@dataclass(frozen=True)
class LiquiditySnapshotData:
    token_address: str
    timestamp: datetime
    pool_address: str
    liquidity_usd: Decimal
    liquidity_sol: Decimal | None
    lp_locked: bool | None
    lp_burned: bool | None
    is_mock: bool
    source: str


@dataclass(frozen=True)
class NarrativeSignal:
    """Social attention data for a narrative/query (PRD S20). Nothing in
    apps/narratives currently REQUIRES this to be non-None -- strength and
    momentum are computed from on-chain proxies when no social provider is
    configured (see apps/narratives/scoring.py) -- but every function that
    accepts one is written to blend it in when available, so a real social
    provider is a config change away, not a rewrite.
    """

    query: str
    timestamp: datetime
    mention_count_current: int
    mention_count_previous: int | None
    unique_accounts_current: int | None
    is_mock: bool
    source: str


@dataclass(frozen=True)
class WalletTransactionData:
    tx_signature: str
    wallet_address: str
    token_address: str
    side: str  # "buy" | "sell"
    amount_tokens: Decimal
    amount_usd: Decimal | None
    price: Decimal | None
    occurred_at: datetime
    is_mock: bool
    source: str

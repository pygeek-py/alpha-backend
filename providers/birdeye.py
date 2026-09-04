"""Real Birdeye-backed providers. Field mappings below were verified against
Birdeye's actual live response shape (probed manually against BONK during
development), not guessed from documentation alone -- see the batch report
for exactly which fields are real vs. unavailable at the current API tier.

Known gaps on the current (free/starter) Birdeye plan:
- /defi/token_security returns 401 (needs a higher tier), so mint/freeze
  authority, LP lock/burn status, and creator/insider holder % are all None
  here rather than fabricated.
- Birdeye has no native 15-minute volume bucket (only 1m/5m/30m/1h/2h/4h/
  8h/24h), so volume_15m is always None from this provider rather than an
  interpolated guess.
- unique_buyers_5m/unique_sellers_5m aren't split by side in Birdeye's
  response (only a combined uniqueWallet5m), so both are None.
"""

import logging
from datetime import datetime
from decimal import Decimal

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from providers.cache_utils import cache_key_for
from providers.exceptions import ProviderError
from providers.interfaces import MarketDataProvider, SolanaDataProvider
from providers.types import DiscoveredToken, HolderDistribution, LiquiditySnapshotData, MarketSnapshotData
from providers.utils import parse_iso, to_decimal

logger = logging.getLogger("alpha.providers.birdeye")

BASE_URL = "https://public-api.birdeye.so"
SOURCE = "birdeye"
TIMEOUT_SECONDS = 10


class BirdeyeClient:
    """Thin HTTP wrapper. `cache_seconds` lets callers memoize a response in
    Redis -- token_overview is used by both market-data and liquidity
    collection, which run on the same schedule and would otherwise double
    Birdeye API usage for every polling cycle on an already rate-limited
    free-tier key (observed 429s hitting two calls seconds apart)."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.BIRDEYE_API_KEY
        if not self.api_key:
            raise ProviderError("BIRDEYE_API_KEY is not configured")

    def get_json(self, path: str, params: dict | None = None, *, cache_seconds: int = 0) -> dict:
        cache_key = None
        if cache_seconds:
            cache_key = cache_key_for("birdeye", path, params)
            cached = cache.get(cache_key)
            if cached is not None:
                return cached

        try:
            response = requests.get(
                f"{BASE_URL}{path}",
                params=params,
                headers={"X-API-KEY": self.api_key, "x-chain": "solana", "accept": "application/json"},
                timeout=TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise ProviderError(f"Birdeye request to {path} failed: {exc}") from exc

        if response.status_code != 200:
            raise ProviderError(f"Birdeye {path} returned {response.status_code}: {response.text[:200]}")

        payload = response.json()
        if not payload.get("success", True):
            raise ProviderError(f"Birdeye {path} reported failure: {payload.get('message')}")
        data = payload["data"]

        if cache_key:
            cache.set(cache_key, data, timeout=cache_seconds)
        return data


class BirdeyeMarketDataProvider(MarketDataProvider):
    def __init__(self, client: BirdeyeClient | None = None):
        self.client = client or BirdeyeClient()

    def get_market_snapshot(self, token_address: str) -> MarketSnapshotData:
        data = self.client.get_json("/defi/token_overview", {"address": token_address}, cache_seconds=30)
        # "extensions" (description/twitter/website/discord) verified present
        # in Birdeye's real live response during development -- see this
        # module's docstring. Not every token has one.
        extensions = data.get("extensions") or {}
        raw_social = {"twitter": extensions.get("twitter"), "discord": extensions.get("discord")}
        social_links = {k: v for k, v in raw_social.items() if v}

        return MarketSnapshotData(
            token_address=token_address,
            timestamp=timezone.now(),
            price=to_decimal(data.get("price")) or Decimal("0"),
            market_cap=to_decimal(data.get("marketCap")),
            volume_1m=to_decimal(data.get("v1mUSD")),
            volume_5m=to_decimal(data.get("v5mUSD")),
            volume_15m=None,
            volume_1h=to_decimal(data.get("v1hUSD")),
            buy_volume_5m=to_decimal(data.get("vBuy5mUSD")),
            sell_volume_5m=to_decimal(data.get("vSell5mUSD")),
            unique_buyers_5m=None,
            unique_sellers_5m=None,
            is_mock=False,
            source=SOURCE,
            description=extensions.get("description") or "",
            website=extensions.get("website") or "",
            social_links=social_links,
        )

    def get_liquidity_snapshot(self, token_address: str) -> LiquiditySnapshotData:
        data = self.client.get_json("/defi/token_overview", {"address": token_address}, cache_seconds=30)
        return LiquiditySnapshotData(
            token_address=token_address,
            timestamp=timezone.now(),
            pool_address="",
            liquidity_usd=to_decimal(data.get("liquidity")) or Decimal("0"),
            liquidity_sol=None,
            lp_locked=None,
            lp_burned=None,
            is_mock=False,
            source=SOURCE,
        )


class BirdeyeSolanaProvider(SolanaDataProvider):
    def __init__(self, client: BirdeyeClient | None = None):
        self.client = client or BirdeyeClient()

    def discover_tokens(self, *, limit: int = 50, since: datetime | None = None) -> list[DiscoveredToken]:
        # Birdeye's own enforced range for this endpoint is 1-20 (confirmed
        # live -- requesting 50 now 400s with "limit should be integer,
        # range 1-20"; either tightened since Batch 3.5 or never actually
        # exercised above 20 until the Batch 21 pipeline endpoint's live
        # test caught it). The caller-facing default stays 50 -- that's the
        # provider-agnostic "how many tokens per cycle" business parameter;
        # this clamp is Birdeye's own API constraint, which belongs here,
        # not leaked into apps/tokens's business logic.
        data = self.client.get_json("/defi/v2/tokens/new_listing", {"limit": min(limit, 20)})
        tokens = []
        for item in data.get("items", []):
            tokens.append(
                DiscoveredToken(
                    address=item["address"],
                    symbol=(item.get("symbol") or "")[:32],
                    name=(item.get("name") or "")[:128],
                    decimals=item.get("decimals", 9),
                    creator_address="",
                    launched_at=parse_iso(item.get("liquidityAddedAt")) or timezone.now(),
                    mint_authority_revoked=None,
                    freeze_authority_revoked=None,
                    is_mutable_metadata=None,
                    top_holder_pct_at_launch=None,
                    is_mock=False,
                    source=SOURCE,
                )
            )
        return tokens

    def get_holder_distribution(self, token_address: str) -> HolderDistribution:
        overview = self.client.get_json(
            "/defi/token_overview", {"address": token_address}, cache_seconds=30
        )
        holder_count = overview.get("holder") or 0
        total_supply = to_decimal(overview.get("totalSupply"))

        top_holder_pct = top5_pct = top10_pct = None
        if total_supply and total_supply > 0:
            holders = self.client.get_json(
                "/defi/v3/token/holder", {"address": token_address, "offset": 0, "limit": 10}
            )
            amounts = [to_decimal(h.get("ui_amount")) or Decimal("0") for h in holders.get("items", [])]
            if amounts:
                top_holder_pct = (amounts[0] / total_supply * 100).quantize(Decimal("0.01"))
                top5_pct = (sum(amounts[:5]) / total_supply * 100).quantize(Decimal("0.01"))
                top10_pct = (sum(amounts[:10]) / total_supply * 100).quantize(Decimal("0.01"))

        return HolderDistribution(
            token_address=token_address,
            timestamp=timezone.now(),
            holder_count=holder_count,
            top_holder_pct=top_holder_pct,
            top5_pct=top5_pct,
            top10_pct=top10_pct,
            creator_pct=None,
            insider_pct=None,
            is_mock=False,
            source=SOURCE,
        )

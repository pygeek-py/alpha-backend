"""HybridSolanaProvider composes Birdeye (discovery, total holder count) with
QuickNode raw RPC (mint/freeze authority, top-holder concentration). Each
upstream is used for the piece it's actually best at:

- Birdeye's /defi/v2/tokens/new_listing is the only practical source of
  "recently created tokens" without running a custom log-subscription
  indexer, so discovery stays Birdeye-driven.
- Mint/freeze authority is read directly from the on-chain SPL Token Mint
  account via QuickNode -- more authoritative than a third party's derived
  security score, and doesn't need Birdeye's gated /defi/token_security tier.
- Top-holder concentration comes from QuickNode's getTokenLargestAccounts
  (up to 20 accounts, no extra load on Birdeye's stricter free-tier rate
  limit); total holder *count* still comes from Birdeye, since raw RPC has
  no equivalent without full account enumeration.

This is registered separately from plain "birdeye" (SOLANA_CHAIN_DATA_PROVIDER
values: "birdeye" vs "birdeye_quicknode") rather than silently upgrading what
"birdeye" means, so switching behavior is always an explicit config choice.
"""

import dataclasses
from datetime import datetime
from decimal import Decimal

from django.utils import timezone

from providers.birdeye import BirdeyeSolanaProvider
from providers.exceptions import ProviderError
from providers.interfaces import SolanaDataProvider
from providers.quicknode import QuickNodeClient
from providers.types import DiscoveredToken, HolderDistribution
from providers.utils import to_decimal

SOURCE = "birdeye+quicknode"


class HybridSolanaProvider(SolanaDataProvider):
    def __init__(
        self,
        birdeye: BirdeyeSolanaProvider | None = None,
        quicknode: QuickNodeClient | None = None,
    ):
        self.birdeye = birdeye or BirdeyeSolanaProvider()
        self.quicknode = quicknode or QuickNodeClient()

    def discover_tokens(self, *, limit: int = 50, since: datetime | None = None) -> list[DiscoveredToken]:
        tokens = self.birdeye.discover_tokens(limit=limit, since=since)
        enriched = []
        for token in tokens:
            try:
                mint_revoked, freeze_revoked = self.quicknode.get_mint_authorities(token.address)
            except ProviderError:
                mint_revoked, freeze_revoked = None, None
            enriched.append(
                dataclasses.replace(
                    token,
                    mint_authority_revoked=mint_revoked,
                    freeze_authority_revoked=freeze_revoked,
                    source=SOURCE,
                )
            )
        return enriched

    def get_holder_distribution(self, token_address: str) -> HolderDistribution:
        # Birdeye's overview call is cached for 30s (see BirdeyeClient), so this
        # is often free if collect_holders and collect_market_data ran recently
        # for the same token.
        holder_count = self.birdeye.get_holder_distribution(token_address).holder_count

        supply_info = self.quicknode.get_token_supply(token_address)
        total_supply = to_decimal(supply_info.get("uiAmount"))

        top_holder_pct = top5_pct = top10_pct = None
        if total_supply and total_supply > 0:
            accounts = self.quicknode.get_token_largest_accounts(token_address)
            amounts = [to_decimal(a.get("uiAmount")) or Decimal("0") for a in accounts]
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

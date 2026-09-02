from decimal import Decimal
from unittest.mock import Mock

import pytest
from django.core.cache import cache

from providers.birdeye import BirdeyeSolanaProvider
from providers.exceptions import ProviderError
from providers.hybrid import HybridSolanaProvider
from providers.quicknode import QuickNodeClient
from providers.types import DiscoveredToken, HolderDistribution

BONK = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _discovered_token(**overrides) -> DiscoveredToken:
    from django.utils import timezone

    defaults = dict(
        address=BONK,
        symbol="BONK",
        name="Bonk",
        decimals=5,
        creator_address="",
        launched_at=timezone.now(),
        mint_authority_revoked=None,
        freeze_authority_revoked=None,
        is_mutable_metadata=None,
        top_holder_pct_at_launch=None,
        is_mock=False,
        source="birdeye",
    )
    defaults.update(overrides)
    return DiscoveredToken(**defaults)


class TestHybridDiscoverTokens:
    def test_enriches_discovered_tokens_with_real_authority_data(self):
        birdeye = Mock(spec=BirdeyeSolanaProvider)
        birdeye.discover_tokens.return_value = [_discovered_token()]

        quicknode = Mock(spec=QuickNodeClient)
        quicknode.get_mint_authorities.return_value = (True, True)

        provider = HybridSolanaProvider(birdeye=birdeye, quicknode=quicknode)
        tokens = provider.discover_tokens(limit=1)

        assert len(tokens) == 1
        assert tokens[0].mint_authority_revoked is True
        assert tokens[0].freeze_authority_revoked is True
        assert tokens[0].source == "birdeye+quicknode"
        # Original Birdeye fields (symbol, address, ...) are preserved.
        assert tokens[0].symbol == "BONK"

    def test_quicknode_failure_leaves_authority_fields_none_not_crashing(self):
        birdeye = Mock(spec=BirdeyeSolanaProvider)
        birdeye.discover_tokens.return_value = [_discovered_token()]

        quicknode = Mock(spec=QuickNodeClient)
        quicknode.get_mint_authorities.side_effect = ProviderError("RPC down")

        provider = HybridSolanaProvider(birdeye=birdeye, quicknode=quicknode)
        tokens = provider.discover_tokens(limit=1)

        assert len(tokens) == 1
        assert tokens[0].mint_authority_revoked is None
        assert tokens[0].freeze_authority_revoked is None


class TestHybridHolderDistribution:
    def test_combines_birdeye_holder_count_with_quicknode_percentages(self):
        birdeye = Mock(spec=BirdeyeSolanaProvider)
        birdeye.get_holder_distribution.return_value = HolderDistribution(
            token_address=BONK,
            timestamp=None,
            holder_count=1009262,
            top_holder_pct=None,
            top5_pct=None,
            top10_pct=None,
            creator_pct=None,
            insider_pct=None,
            is_mock=False,
            source="birdeye",
        )

        quicknode = Mock(spec=QuickNodeClient)
        quicknode.get_token_supply.return_value = {"uiAmount": 100_000.0}
        quicknode.get_token_largest_accounts.return_value = [
            {"uiAmount": 10_000.0},
            {"uiAmount": 5_000.0},
        ]

        provider = HybridSolanaProvider(birdeye=birdeye, quicknode=quicknode)
        dist = provider.get_holder_distribution(BONK)

        assert dist.holder_count == 1009262  # from Birdeye
        assert dist.top_holder_pct == Decimal("10.00")  # from QuickNode: 10000/100000*100
        assert dist.source == "birdeye+quicknode"

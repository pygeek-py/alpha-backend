"""Fixture-backed provider implementations. No network calls, ever.

Every value is derived from a seeded RNG rather than true randomness: a
per-token "base" seed (hash of the address alone) gives each token stable
underlying characteristics across calls, and a per-time-bucket seed (address
+ current 5-minute window) layers in gradual drift on top -- so polling the
same token repeatedly over time produces a plausible, evolving trajectory
instead of either frozen or purely noisy data. This is what "controlled
mock/fixture support" (PRD Batch 3) means in practice: deterministic,
reproducible, and clearly labeled (is_mock=True, source="mock") rather than
made to look like real production data.
"""

import hashlib
import random
from datetime import datetime, timedelta
from decimal import Decimal

from django.utils import timezone

from providers.interfaces import (
    MarketDataProvider,
    SocialDataProvider,
    SolanaDataProvider,
    WalletDataProvider,
)
from providers.types import (
    DiscoveredToken,
    HolderDistribution,
    LiquiditySnapshotData,
    MarketSnapshotData,
    NarrativeSignal,
    WalletTransactionData,
)

_NAME_PARTS = [
    "Doge", "Pepe", "Wojak", "Moon", "Rocket", "Cat", "Frog", "Chad", "Based",
    "Turbo", "Giga", "Ninja", "Sigma", "Alpha", "Meme", "Solar", "Nova",
    "Pump", "Bonk", "Wif",
]
_ADDRESS_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

# Narrative-flavored description templates, keyed by category -- so mock data
# can actually exercise narrative detection (Batch 7) in local dev/demos
# instead of every token having a blank/generic description. About 40% of
# mock tokens get a themed description (see get_market_snapshot); the rest
# stay blank, simulating tokens with no clear narrative.
_NARRATIVE_DESCRIPTION_TEMPLATES = {
    "ai": "An AI-powered autonomous agent bringing machine intelligence to Solana trading.",
    "gaming": "The official token for our blockchain gaming metaverse and play-to-earn ecosystem.",
    "politics": "A political satire meme token riffing on the latest election headlines.",
    "animals": "A community-driven dog-themed meme coin with a loyal pack of holders.",
    "celebrity": "Inspired by a viral celebrity moment that broke the internet this week.",
}


def _seed_for(*parts: str) -> int:
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return int(digest[:8], 16)


def _time_bucket(now: datetime, minutes: int = 5) -> str:
    floored_minute = (now.minute // minutes) * minutes
    return now.replace(minute=floored_minute, second=0, microsecond=0).isoformat()


def _fake_address(rng: random.Random) -> str:
    return "".join(rng.choice(_ADDRESS_ALPHABET) for _ in range(44))


def _decimal(value: float, places: int = 6) -> Decimal:
    return Decimal(str(round(value, places)))


class MockSolanaProvider(SolanaDataProvider):
    def discover_tokens(self, *, limit: int = 50, since: datetime | None = None) -> list[DiscoveredToken]:
        now = timezone.now()
        bucket = _time_bucket(now)
        tokens = []
        for i in range(limit):
            rng = random.Random(_seed_for("discover", bucket, str(i)))
            symbol = rng.choice(_NAME_PARTS) + rng.choice(_NAME_PARTS)
            address = _fake_address(rng)
            creator_rng = random.Random(_seed_for("creator", address))
            age_seconds = rng.randint(0, 3600)
            tokens.append(
                DiscoveredToken(
                    address=address,
                    symbol=symbol[:10].upper(),
                    name=f"{symbol} Token",
                    decimals=9,
                    creator_address=_fake_address(creator_rng),
                    launched_at=now - timedelta(seconds=age_seconds),
                    mint_authority_revoked=rng.random() > 0.2,
                    freeze_authority_revoked=rng.random() > 0.15,
                    is_mutable_metadata=rng.random() > 0.7,
                    top_holder_pct_at_launch=_decimal(rng.uniform(5, 40), 2),
                    is_mock=True,
                    source="mock",
                )
            )
        return tokens

    def get_holder_distribution(self, token_address: str) -> HolderDistribution:
        now = timezone.now()
        base_rng = random.Random(_seed_for("holders_base", token_address))
        drift_rng = random.Random(_seed_for("holders_drift", token_address, _time_bucket(now)))

        base_holders = base_rng.randint(20, 2000)
        holder_count = max(1, base_holders + drift_rng.randint(-10, 40))
        # The floor must apply to the value AFTER adding drift, not before --
        # flooring the base term alone still let the subsequent +/-2 drift
        # push the final result negative.
        raw_top_holder_pct = 40 / (1 + holder_count / 50) + drift_rng.uniform(-2, 2)
        top_holder_pct = _decimal(max(0.5, raw_top_holder_pct), 2)

        return HolderDistribution(
            token_address=token_address,
            timestamp=now,
            holder_count=holder_count,
            top_holder_pct=top_holder_pct,
            top5_pct=min(Decimal("100"), top_holder_pct * Decimal("2.2")),
            top10_pct=min(Decimal("100"), top_holder_pct * Decimal("3.1")),
            creator_pct=_decimal(base_rng.uniform(0, 8), 2),
            insider_pct=_decimal(base_rng.uniform(0, 5), 2),
            is_mock=True,
            source="mock",
        )


class MockMarketDataProvider(MarketDataProvider):
    def get_market_snapshot(self, token_address: str) -> MarketSnapshotData:
        now = timezone.now()
        base_rng = random.Random(_seed_for("market_base", token_address))
        drift_rng = random.Random(_seed_for("market_drift", token_address, _time_bucket(now)))

        base_price = base_rng.uniform(0.0000001, 0.01)
        drift_multiplier = drift_rng.uniform(0.85, 1.20)
        price = _decimal(base_price * drift_multiplier, 18)

        supply = base_rng.randint(1_000_000, 1_000_000_000)
        market_cap = _decimal(float(price) * supply, 2)

        volume_5m = _decimal(drift_rng.uniform(500, 50_000), 2)
        buy_share = drift_rng.uniform(0.35, 0.7)
        buy_volume_5m = _decimal(float(volume_5m) * buy_share, 2)
        sell_volume_5m = _decimal(float(volume_5m) - float(buy_volume_5m), 2)

        description = ""
        website = ""
        social_links = {}
        if base_rng.random() < 0.4:
            category = base_rng.choice(list(_NARRATIVE_DESCRIPTION_TEMPLATES))
            description = _NARRATIVE_DESCRIPTION_TEMPLATES[category]
            website = f"https://{token_address[:10].lower()}.example"
            social_links = {"twitter": f"https://twitter.com/{token_address[:10].lower()}"}

        return MarketSnapshotData(
            token_address=token_address,
            timestamp=now,
            price=price,
            market_cap=market_cap,
            volume_1m=_decimal(float(volume_5m) / 5, 2),
            volume_5m=volume_5m,
            volume_15m=_decimal(float(volume_5m) * 2.6, 2),
            volume_1h=_decimal(float(volume_5m) * 8, 2),
            buy_volume_5m=buy_volume_5m,
            sell_volume_5m=sell_volume_5m,
            unique_buyers_5m=drift_rng.randint(5, 200),
            unique_sellers_5m=drift_rng.randint(3, 150),
            is_mock=True,
            source="mock",
            description=description,
            website=website,
            social_links=social_links,
        )

    def get_liquidity_snapshot(self, token_address: str) -> LiquiditySnapshotData:
        now = timezone.now()
        base_rng = random.Random(_seed_for("liquidity_base", token_address))
        drift_rng = random.Random(_seed_for("liquidity_drift", token_address, _time_bucket(now)))

        base_liquidity = base_rng.uniform(5_000, 500_000)
        drift_multiplier = drift_rng.uniform(0.9, 1.1)
        liquidity_usd = _decimal(base_liquidity * drift_multiplier, 2)

        return LiquiditySnapshotData(
            token_address=token_address,
            timestamp=now,
            pool_address=_fake_address(random.Random(_seed_for("pool", token_address))),
            liquidity_usd=liquidity_usd,
            liquidity_sol=_decimal(float(liquidity_usd) / 180, 9),
            lp_locked=base_rng.random() > 0.3,
            lp_burned=base_rng.random() > 0.6,
            is_mock=True,
            source="mock",
        )


_RECURRING_WALLET_POOL_SIZE = 25
_RECURRING_WALLET_SHARE = 0.5  # fraction of tx slots drawn from the pool vs. a fresh one-off address


def _recurring_wallet_pool() -> list[str]:
    """A fixed-size pool of wallet addresses that recur across many tokens
    and calls (unlike the rest of the mock data, this pool is NOT seeded by
    token/time-bucket) -- without it, every mock transaction gets a
    brand-new random wallet and no wallet ever accumulates enough history
    for cross-token classification signals (smart money, sniper, bot) to
    have anything to work with in local dev/demos."""
    return [_fake_address(random.Random(_seed_for("recurring_wallet", str(i)))) for i in range(
        _RECURRING_WALLET_POOL_SIZE
    )]


class MockWalletDataProvider(WalletDataProvider):
    def get_recent_transactions(
        self, token_address: str, *, limit: int = 50, since: datetime | None = None
    ) -> list[WalletTransactionData]:
        now = timezone.now()
        bucket = _time_bucket(now)
        pool = _recurring_wallet_pool()
        transactions = []
        for i in range(min(limit, 20)):
            rng = random.Random(_seed_for("tx", token_address, bucket, str(i)))
            if rng.random() < _RECURRING_WALLET_SHARE:
                wallet_address = pool[rng.randrange(len(pool))]
            else:
                wallet_address = _fake_address(rng)
            side = "buy" if rng.random() > 0.45 else "sell"
            amount_tokens = _decimal(rng.uniform(1_000, 5_000_000), 9)
            price = _decimal(rng.uniform(0.0000001, 0.01), 18)
            transactions.append(
                WalletTransactionData(
                    tx_signature=hashlib.sha256(
                        f"{token_address}|{bucket}|{i}".encode()
                    ).hexdigest(),
                    wallet_address=wallet_address,
                    token_address=token_address,
                    side=side,
                    amount_tokens=amount_tokens,
                    amount_usd=_decimal(float(amount_tokens) * float(price), 2),
                    price=price,
                    occurred_at=now - timedelta(seconds=rng.randint(0, 300)),
                    is_mock=True,
                    source="mock",
                )
            )
        return transactions


class MockSocialDataProvider(SocialDataProvider):
    """Deterministic simulated mention data -- clearly labeled is_mock=True,
    never to be confused with a real social listening integration. Exists so
    the "if a social provider is configured" code paths in
    apps/narratives/scoring.py are actually exercised in dev/tests, not just
    unreachable branches."""

    def get_mention_signal(self, query: str) -> NarrativeSignal | None:
        now = timezone.now()
        base_rng = random.Random(_seed_for("social_base", query))
        drift_rng = random.Random(_seed_for("social_drift", query, _time_bucket(now)))

        base_mentions = base_rng.randint(5, 500)
        current = max(0, base_mentions + drift_rng.randint(-50, 150))
        previous = max(0, base_mentions + drift_rng.randint(-50, 50))

        return NarrativeSignal(
            query=query,
            timestamp=now,
            mention_count_current=current,
            mention_count_previous=previous,
            unique_accounts_current=max(0, int(current * base_rng.uniform(0.3, 0.7))),
            is_mock=True,
            source="mock",
        )

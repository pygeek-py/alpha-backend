from django.db import models

from apps.core.fields import multiple_field, percentage_field, price_field, usd_field
from apps.core.models import SourcedModel, TimestampedModel
from apps.tokens.models import Token


class Wallet(SourcedModel):
    """A Solana wallet being tracked for behavior/performance analysis.

    `classification` starts as UNKNOWN and is set by the wallet-intelligence
    engine (Batch 6) -- profitability alone must never imply SMART_MONEY, per
    the PRD's explicit warning against blindly copying wallets.
    """

    class Classification(models.TextChoices):
        SMART_MONEY = "smart_money", "Smart Money"
        INSIDER = "insider", "Insider"
        CREATOR = "creator", "Creator"
        SNIPER = "sniper", "Sniper"
        BOT = "bot", "Bot"
        BUNDLED = "bundled", "Bundled Wallet"
        MARKET_MAKER = "market_maker", "Market Maker"
        NORMAL = "normal", "Normal Trader"
        UNKNOWN = "unknown", "Unknown"

    address = models.CharField(max_length=64, unique=True, db_index=True)
    label = models.CharField(max_length=128, blank=True)
    classification = models.CharField(
        max_length=20, choices=Classification.choices, default=Classification.UNKNOWN, db_index=True
    )
    classification_confidence = percentage_field(null=True, blank=True)
    classification_reasons = models.JSONField(default=list, blank=True)
    first_seen_at = models.DateTimeField(null=True, blank=True)
    cluster = models.ForeignKey(
        "WalletCluster", on_delete=models.SET_NULL, null=True, blank=True, related_name="wallets"
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.label or self.address[:8]


class WalletTransaction(SourcedModel):
    class Side(models.TextChoices):
        BUY = "buy", "Buy"
        SELL = "sell", "Sell"

    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name="transactions")
    token = models.ForeignKey(Token, on_delete=models.CASCADE, related_name="wallet_transactions")
    tx_signature = models.CharField(max_length=128, unique=True, db_index=True)

    side = models.CharField(max_length=4, choices=Side.choices)
    amount_tokens = models.DecimalField(max_digits=36, decimal_places=9)
    amount_usd = usd_field(null=True, blank=True)
    price = price_field(null=True, blank=True)

    occurred_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["wallet", "-occurred_at"]),
            models.Index(fields=["token", "-occurred_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.wallet} {self.side} {self.token} @ {self.occurred_at:%Y-%m-%d %H:%M}"


class WalletPerformance(TimestampedModel):
    """Rolling performance rollup for a wallet, recomputed periodically by
    calculate_wallet_reputation (Batch 6). One row per wallet, updated in
    place -- this is a summary, not a time series; the transactions it's
    computed from are the time series."""

    class PreferredAgeBucket(models.TextChoices):
        EARLY = "0_5m", "0-5 minutes"
        RECENT = "5_30m", "5-30 minutes"
        ESTABLISHED = "30m_3h", "30 minutes - 3 hours"
        MATURE = "3h_plus", "3+ hours"

    wallet = models.OneToOneField(Wallet, on_delete=models.CASCADE, related_name="performance")

    win_rate = percentage_field(null=True, blank=True)
    avg_multiple = multiple_field(null=True, blank=True)
    median_multiple = multiple_field(null=True, blank=True)
    max_multiple = multiple_field(null=True, blank=True)
    avg_holding_time = models.DurationField(null=True, blank=True)

    trade_count = models.PositiveIntegerField(default=0)
    successful_2x_count = models.PositiveIntegerField(default=0)
    successful_3x_count = models.PositiveIntegerField(default=0)
    successful_5x_count = models.PositiveIntegerField(default=0)

    preferred_token_age = models.CharField(
        max_length=10, choices=PreferredAgeBucket.choices, blank=True
    )
    preferred_market_cap_range = models.CharField(max_length=32, blank=True)

    reputation_score = percentage_field(null=True, blank=True, help_text="0-100 smart-money wallet score")
    last_calculated_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.wallet} performance"


class WalletCluster(TimestampedModel):
    """A group of wallets whose transaction timing suggests they're operated
    by the same entity (PRD S18's "wallet clustering foundations") -- e.g.
    multiple wallets buying the same tokens within seconds of each other,
    repeatedly, across several unrelated launches. This is a first,
    explainable heuristic (see apps/wallets/clustering.py), not a claim of
    certainty -- `confidence` and `shared_token_count` are exposed so
    consumers can judge how strong the grouping evidence actually is.
    """

    label = models.CharField(max_length=64, blank=True)
    shared_token_count = models.PositiveIntegerField(default=0)
    confidence = percentage_field(null=True, blank=True)
    detected_at = models.DateTimeField()

    def __str__(self) -> str:
        return self.label or f"Cluster #{self.pk}"

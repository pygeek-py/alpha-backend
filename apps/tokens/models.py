from django.db import models

from apps.core.fields import percentage_field
from apps.core.models import SourcedModel


class Token(SourcedModel):
    """A Solana token's identity. Immutable-ish facts about the mint itself --
    everything that changes over time (price, liquidity, holders, ...) lives
    in the *Snapshot models in market_data/liquidity/holders instead."""

    address = models.CharField(max_length=64, unique=True, db_index=True)
    symbol = models.CharField(max_length=32, blank=True)
    name = models.CharField(max_length=128, blank=True)
    decimals = models.PositiveSmallIntegerField(default=9)

    # Identity metadata used by narrative detection (PRD S21: name, symbol,
    # description, website, social profiles). Populated incidentally by
    # collect_market_data when the provider's response happens to include it
    # (Birdeye's token_overview does) -- not worth a dedicated fetch/API call
    # of its own.
    description = models.TextField(blank=True)
    website = models.CharField(max_length=255, blank=True)
    social_links = models.JSONField(
        default=dict, blank=True, help_text='e.g. {"twitter": "...", "discord": "..."}'
    )

    creator_address = models.CharField(max_length=64, blank=True, db_index=True)
    launched_at = models.DateTimeField(null=True, blank=True, help_text="On-chain mint creation time")

    # Safety-relevant facts about the mint itself (see scoring.TokenScore for
    # the computed safety score built from these plus liquidity/holder data).
    mint_authority_revoked = models.BooleanField(null=True, blank=True)
    freeze_authority_revoked = models.BooleanField(null=True, blank=True)
    is_mutable_metadata = models.BooleanField(null=True, blank=True)
    top_holder_pct_at_launch = percentage_field(null=True, blank=True)

    is_active = models.BooleanField(
        default=True, db_index=True, help_text="Still being actively monitored/ingested"
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["is_active", "-created_at"]),
        ]

    def __str__(self) -> str:
        return self.symbol or self.address[:8]

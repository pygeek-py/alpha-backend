from django.db import models

from apps.core.fields import price_field, usd_field
from apps.core.models import SourcedModel
from apps.tokens.models import Token


class TokenSnapshot(SourcedModel):
    """Observed price/market-cap/volume state of a token at a point in time.

    Deliberately covers both what the PRD's model list calls "TokenSnapshot"
    and "VolumeSnapshot" -- they'd otherwise be two time-series tables sampled
    at the same cadence for the same token, which is redundant. Volume windows
    live here as plain observed values; derived metrics (acceleration, buy
    pressure trend, etc.) are computed from consecutive snapshots by the
    scoring/prediction feature-extraction services, not stored as raw fields.
    """

    token = models.ForeignKey(Token, on_delete=models.CASCADE, related_name="snapshots")
    timestamp = models.DateTimeField(db_index=True)

    price = price_field()
    market_cap = usd_field(null=True, blank=True)

    volume_1m = usd_field(null=True, blank=True)
    volume_5m = usd_field(null=True, blank=True)
    volume_15m = usd_field(null=True, blank=True)
    volume_1h = usd_field(null=True, blank=True)

    buy_volume_5m = usd_field(null=True, blank=True)
    sell_volume_5m = usd_field(null=True, blank=True)
    unique_buyers_5m = models.PositiveIntegerField(null=True, blank=True)
    unique_sellers_5m = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [models.Index(fields=["token", "-timestamp"])]
        constraints = [
            models.UniqueConstraint(fields=["token", "timestamp", "source"], name="unique_token_snapshot")
        ]

    def __str__(self) -> str:
        return f"{self.token} @ {self.timestamp:%Y-%m-%d %H:%M}"

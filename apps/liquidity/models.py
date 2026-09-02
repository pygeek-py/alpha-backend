from django.db import models

from apps.core.fields import usd_field
from apps.core.models import SourcedModel
from apps.tokens.models import Token


class LiquiditySnapshot(SourcedModel):
    """Observed liquidity state of a token's primary pool at a point in time."""

    token = models.ForeignKey(Token, on_delete=models.CASCADE, related_name="liquidity_snapshots")
    timestamp = models.DateTimeField(db_index=True)

    pool_address = models.CharField(max_length=64, blank=True)
    liquidity_usd = usd_field()
    liquidity_sol = models.DecimalField(max_digits=24, decimal_places=9, null=True, blank=True)

    lp_locked = models.BooleanField(null=True, blank=True)
    lp_burned = models.BooleanField(null=True, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [models.Index(fields=["token", "-timestamp"])]
        constraints = [
            models.UniqueConstraint(
                fields=["token", "timestamp", "source"], name="unique_liquidity_snapshot"
            )
        ]

    def __str__(self) -> str:
        return f"{self.token} liquidity @ {self.timestamp:%Y-%m-%d %H:%M}"

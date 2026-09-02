from django.db import models

from apps.core.fields import percentage_field
from apps.core.models import SourcedModel
from apps.tokens.models import Token


class HolderSnapshot(SourcedModel):
    """Observed holder distribution of a token at a point in time."""

    token = models.ForeignKey(Token, on_delete=models.CASCADE, related_name="holder_snapshots")
    timestamp = models.DateTimeField(db_index=True)

    holder_count = models.PositiveIntegerField()
    top_holder_pct = percentage_field(null=True, blank=True)
    top5_pct = percentage_field(null=True, blank=True)
    top10_pct = percentage_field(null=True, blank=True)
    creator_pct = percentage_field(null=True, blank=True)
    insider_pct = percentage_field(null=True, blank=True, help_text="From wallet clustering, if known")

    class Meta:
        ordering = ["-timestamp"]
        indexes = [models.Index(fields=["token", "-timestamp"])]
        constraints = [
            models.UniqueConstraint(fields=["token", "timestamp", "source"], name="unique_holder_snapshot")
        ]

    def __str__(self) -> str:
        return f"{self.token} holders @ {self.timestamp:%Y-%m-%d %H:%M}"

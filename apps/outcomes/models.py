from django.db import models

from apps.alerts.models import Alert
from apps.core.fields import multiple_field, price_field, usd_field
from apps.core.models import TimestampedModel
from apps.predictions.models import Prediction
from apps.tokens.models import Token


class TokenOutcome(TimestampedModel):
    """Summary/label record for what actually happened after a signal
    (PRD S26-28, S51).

    Batch 2 originally anchored this to Prediction (every prediction needs
    outcome tracking regardless of whether it became a user-facing alert --
    PRD S6, S28). But Batch 11 (this tracking engine) is scheduled before
    Batch 12 (the Prediction Engine) in the batch plan, so no Prediction rows
    exist yet to anchor to -- a hard dependency conflict, flagged to and
    resolved with the user rather than silently worked around. `alert` (which
    DOES exist, from Batch 10) is now the required anchor instead: PRD S57's
    own framing of alert quality measurement is already alert-anchored
    ("Alerts sent -> Tokens reaching 2x -> Tokens reaching 3x"). `prediction`
    becomes optional, backfilled once Batch 12 ships real predictions.

    This is the OBSERVATION/PREDICTION vs OUTCOME boundary: everything here
    is strictly "what happened after," never mixed with what was known at
    alert/prediction time (that's Prediction.feature_snapshot).
    """

    token = models.ForeignKey(Token, on_delete=models.CASCADE, related_name="outcomes")
    alert = models.OneToOneField(Alert, on_delete=models.CASCADE, related_name="outcome")
    prediction = models.OneToOneField(
        Prediction, on_delete=models.SET_NULL, null=True, blank=True, related_name="outcome"
    )

    reference_timestamp = models.DateTimeField(db_index=True)
    initial_price = price_field()
    initial_market_cap = usd_field(null=True, blank=True)

    max_multiple = multiple_field(null=True, blank=True)
    max_drawdown_pct = multiple_field(null=True, blank=True)

    reached_1_5x = models.BooleanField(default=False)
    reached_2x = models.BooleanField(default=False)
    reached_3x = models.BooleanField(default=False)
    reached_5x = models.BooleanField(default=False)
    reached_10x = models.BooleanField(default=False)

    time_to_2x = models.DurationField(null=True, blank=True)
    time_to_3x = models.DurationField(null=True, blank=True)
    time_to_5x = models.DurationField(null=True, blank=True)

    tracking_complete = models.BooleanField(default=False, db_index=True)
    last_outcome_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-reference_timestamp"]
        indexes = [models.Index(fields=["tracking_complete", "reference_timestamp"])]

    def __str__(self) -> str:
        return f"{self.token} outcome @ {self.reference_timestamp:%Y-%m-%d %H:%M}"


class TokenOutcomeSnapshot(TimestampedModel):
    """One row per fixed tracking offset (PRD S26) for a TokenOutcome. The
    periodic outcome-tracking sweep (Batch 11/Batch 5 of ARCHITECTURE.md)
    creates these as each offset comes due, rather than scheduling a separate
    Celery task per offset per token."""

    class Offset(models.TextChoices):
        M5 = "5m", "5 minutes"
        M10 = "10m", "10 minutes"
        M15 = "15m", "15 minutes"
        M30 = "30m", "30 minutes"
        H1 = "1h", "1 hour"
        H3 = "3h", "3 hours"
        H6 = "6h", "6 hours"
        H12 = "12h", "12 hours"
        H24 = "24h", "24 hours"

    outcome = models.ForeignKey(TokenOutcome, on_delete=models.CASCADE, related_name="snapshots")
    offset_label = models.CharField(max_length=4, choices=Offset.choices)
    recorded_at = models.DateTimeField()

    price = price_field(null=True, blank=True)
    market_cap = usd_field(null=True, blank=True)
    liquidity_usd = usd_field(null=True, blank=True)
    volume_usd = usd_field(null=True, blank=True)
    holder_count = models.PositiveIntegerField(null=True, blank=True)

    max_gain_pct = multiple_field(null=True, blank=True)
    max_drawdown_pct = multiple_field(null=True, blank=True)

    class Meta:
        ordering = ["outcome", "recorded_at"]
        constraints = [
            models.UniqueConstraint(fields=["outcome", "offset_label"], name="unique_outcome_offset")
        ]

    def __str__(self) -> str:
        return f"{self.outcome} +{self.offset_label}"

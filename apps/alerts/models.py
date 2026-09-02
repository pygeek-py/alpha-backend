from django.db import models

from apps.core.fields import percentage_field, probability_field
from apps.core.models import TimestampedModel
from apps.predictions.models import Prediction
from apps.tokens.models import Token


class AlertState(models.TextChoices):
    """PRD S30 alert state machine. A token's *current* state is derived as
    the latest AlertEvent.to_state for that token -- there's no separate
    mutable "current state" column on Token, since the append-only event log
    is both the source of truth and exactly what the anti-spam system
    (cooldowns, signal delta) built in Batch 10 needs to query."""

    DISCOVERED = "discovered", "Discovered"
    WATCHING = "watching", "Watching"
    DEVELOPING = "developing", "Developing"
    CONFIRMED = "confirmed", "Confirmed"
    BREAKOUT = "breakout", "Breakout"
    INVALIDATED = "invalidated", "Invalidated"


class AlertEvent(TimestampedModel):
    """Append-only log of every state transition for a token. Not every event
    produces a user-facing Alert (e.g. DISCOVERED -> WATCHING usually doesn't)
    -- this is the full audit trail; Alert is the subset that surfaced to the
    user/Telegram."""

    token = models.ForeignKey(Token, on_delete=models.CASCADE, related_name="alert_events")
    from_state = models.CharField(max_length=12, choices=AlertState.choices, blank=True)
    to_state = models.CharField(max_length=12, choices=AlertState.choices)
    score = percentage_field(null=True, blank=True)
    reasons = models.JSONField(default=list, blank=True, help_text="List of why-now reason strings")
    triggered_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["-triggered_at"]
        indexes = [models.Index(fields=["token", "-triggered_at"])]

    def __str__(self) -> str:
        return f"{self.token} {self.from_state or '-'} -> {self.to_state}"


class Alert(TimestampedModel):
    """A user-facing alert (dashboard and/or Telegram) generated from an
    AlertEvent. Probabilities/score are captured here at alert time --
    intentionally denormalized from Prediction/TokenScore so this record
    always reflects exactly what the user was shown, even if later
    predictions supersede it."""

    token = models.ForeignKey(Token, on_delete=models.CASCADE, related_name="alerts")
    alert_event = models.ForeignKey(
        AlertEvent, on_delete=models.SET_NULL, null=True, blank=True, related_name="alerts"
    )
    prediction = models.ForeignKey(
        Prediction, on_delete=models.SET_NULL, null=True, blank=True, related_name="alerts"
    )

    state = models.CharField(max_length=12, choices=AlertState.choices, db_index=True)
    score = percentage_field(null=True, blank=True)
    risk_score = percentage_field(null=True, blank=True)
    probability_2x = probability_field(null=True, blank=True)
    probability_3x = probability_field(null=True, blank=True)

    narrative_summary = models.CharField(max_length=255, blank=True)
    reasons = models.JSONField(default=list, blank=True)
    is_priority = models.BooleanField(default=False)

    telegram_sent = models.BooleanField(default=False, db_index=True)
    telegram_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["token", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.token} {self.state} alert"

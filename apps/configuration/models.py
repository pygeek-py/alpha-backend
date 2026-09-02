from django.db import models

from apps.core.fields import percentage_field, probability_field, usd_field
from apps.core.models import TimestampedModel


class AutonomyMode(models.TextChoices):
    AI_AUTOMATIC = "ai_automatic", "AI Automatic"
    AI_RECOMMENDED = "ai_recommended", "AI Recommended"
    MANUAL = "manual", "Manual"


class SystemConfiguration(TimestampedModel):
    """The live, currently-active tunable thresholds (PRD S44). A single
    evolving row rather than versioned rows -- it's read on every alert
    decision, so it needs to be a cheap direct lookup; ConfigurationChange
    below is what carries the full version history/audit trail.

    Default autonomy is AI_AUTOMATIC per the PRD and the explicit decision in
    ARCHITECTURE.md S10 -- the system can change these values on its own once
    the AI configuration engine (Batch 9) exists, with every change audited.
    """

    min_liquidity_usd = usd_field(default=0)
    min_volume_5m_usd = usd_field(default=0)
    min_holder_count = models.PositiveIntegerField(default=0)
    max_risk_score = percentage_field(default=100)
    min_opportunity_score = percentage_field(default=0)
    min_probability_2x = probability_field(default=0)
    min_probability_3x = probability_field(default=0)

    alert_cooldown_minutes = models.PositiveIntegerField(default=20)
    max_alerts_per_hour = models.PositiveIntegerField(default=5)

    narrative_settings = models.JSONField(default=dict, blank=True)
    smart_money_settings = models.JSONField(default=dict, blank=True)

    autonomy_mode = models.CharField(
        max_length=16, choices=AutonomyMode.choices, default=AutonomyMode.AI_AUTOMATIC
    )
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return f"Configuration ({self.autonomy_mode})"


class ConfigurationChangeSource(models.TextChoices):
    AI_AUTOMATIC = "ai_automatic", "AI Automatic"
    AI_RECOMMENDED_APPROVED = "ai_recommended_approved", "AI Recommended, User Approved"
    MANUAL = "manual", "Manual"


class ConfigurationChange(TimestampedModel):
    """Append-only audit trail for every configuration change (PRD S44):
    previous config, new config, reason, expected vs. actual improvement,
    and which rule/model version made the recommendation. This is what makes
    AI_AUTOMATIC mode safe to default to -- every silent change is traceable.
    """

    previous_config = models.JSONField()
    new_config = models.JSONField()
    changed_fields = models.JSONField(default=list, blank=True)
    reason = models.TextField(blank=True)
    expected_improvement = models.JSONField(default=dict, blank=True)
    actual_improvement = models.JSONField(default=dict, blank=True)
    change_source = models.CharField(max_length=32, choices=ConfigurationChangeSource.choices)
    model_version = models.CharField(max_length=32, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Config change ({self.change_source}) @ {self.created_at:%Y-%m-%d %H:%M}"

from django.db import models

from apps.core.fields import percentage_field
from apps.core.models import TimestampedModel
from apps.tokens.models import Token

# Suggested starting categories (PRD S19). Deliberately NOT enforced as DB
# choices on Narrative.category -- the PRD explicitly warns against hardcoding
# a small fixed narrative list, so category stays a free CharField and this
# tuple is just a seed list for the detection engine built in Batch 7.
SUGGESTED_NARRATIVE_CATEGORIES = (
    "ai",
    "politics",
    "celebrity",
    "gaming",
    "animals",
    "current_events",
    "internet_memes",
    "viral_trends",
    "community_driven",
    "cultural_trends",
    "copycat",
    "unknown",
)


class Narrative(TimestampedModel):
    """A detected narrative/theme (e.g. "AI Agents", "Political Meme 2026").
    `category` is a broad grouping; `name` is the specific narrative.

    `keywords` is what makes this "a scalable narrative architecture" rather
    than a hardcoded list (PRD S19): detection triggers are DATA on this
    model, editable via admin/API, not a Python constant requiring a code
    deploy to extend. See apps/narratives/detection.py for how they're used.
    """

    name = models.CharField(max_length=128, unique=True)
    category = models.CharField(max_length=32, db_index=True)
    description = models.TextField(blank=True)
    keywords = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class TokenNarrative(TimestampedModel):
    """Current narrative classification for a token. One row per (token,
    narrative) pair, updated in place as scores change -- historical
    narrative-score tracking isn't needed as its own time series because
    point-in-time values that matter for ML are captured in
    predictions.Prediction.feature_snapshot instead."""

    token = models.ForeignKey(Token, on_delete=models.CASCADE, related_name="narrative_links")
    narrative = models.ForeignKey(Narrative, on_delete=models.CASCADE, related_name="token_links")

    relevance_score = percentage_field(null=True, blank=True)
    strength_score = percentage_field(null=True, blank=True)
    momentum_score = percentage_field(null=True, blank=True)
    detected_at = models.DateTimeField()

    class Meta:
        ordering = ["-detected_at"]
        constraints = [
            models.UniqueConstraint(fields=["token", "narrative"], name="unique_token_narrative")
        ]

    def __str__(self) -> str:
        return f"{self.token} -> {self.narrative}"

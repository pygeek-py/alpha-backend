from django.db import models

from apps.core.fields import percentage_field
from apps.core.models import TimestampedModel
from apps.tokens.models import Token


class TokenScore(TimestampedModel):
    """A weighted score snapshot for a token (PRD S23-24). One row per
    computation -- scores are time-series, not a current-state singleton,
    since historical score trajectories feed both alerting (signal delta)
    and backtesting.

    `explanation` holds the positive/negative/missing factor breakdown
    required for explainability (PRD S54): {"positive": [...], "negative":
    [...], "missing": [...]}.
    """

    token = models.ForeignKey(Token, on_delete=models.CASCADE, related_name="scores")
    timestamp = models.DateTimeField(db_index=True)

    # Nullable (revised from Batch 2's original non-nullable fields): the
    # scoring engine (Batch 8) can legitimately have NO data for a category
    # (e.g. no liquidity snapshot yet) and must be able to record that
    # honestly as "unknown" rather than fabricating a 0, which would read as
    # "very bad" instead of "not computed." The weighted aggregate
    # renormalizes over whatever categories ARE non-null -- see
    # apps/scoring/engine.py.
    safety_score = percentage_field(null=True, blank=True)
    liquidity_score = percentage_field(null=True, blank=True)
    momentum_score = percentage_field(null=True, blank=True)
    holder_growth_score = percentage_field(null=True, blank=True)
    wallet_score = percentage_field(null=True, blank=True)
    buy_pressure_score = percentage_field(null=True, blank=True)
    price_structure_score = percentage_field(null=True, blank=True)
    narrative_score = percentage_field(null=True, blank=True)
    creator_score = percentage_field(null=True, blank=True)

    opportunity_score = percentage_field(db_index=True)
    risk_score = percentage_field()
    # Unlike the per-category fields above, these are never None: the
    # weighted aggregate always returns a real number (0 in the total-
    # absence-of-data case), so non-nullable-with-default is the right shape.
    score_2x = percentage_field(
        default=0,
        help_text="Deterministic 0-100 score, NOT a calibrated probability -- "
        "see Prediction.probability_2x (Batch 12) for that.",
    )
    score_3x = percentage_field(
        default=0,
        help_text="Deterministic 0-100 score, NOT a calibrated probability -- "
        "see Prediction.probability_3x (Batch 12) for that.",
    )

    weights_version = models.CharField(max_length=32, default="v1")
    explanation = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [models.Index(fields=["token", "-timestamp"])]

    def __str__(self) -> str:
        return f"{self.token} score={self.opportunity_score} @ {self.timestamp:%Y-%m-%d %H:%M}"


class TokenSafetyCheck(TimestampedModel):
    """Detailed output of the Token Safety Engine (PRD S11), one row per
    analysis run.

    Batch 2 deliberately did NOT create a separate safety model -- safety was
    treated as just one more number among TokenScore's nine weighted
    categories. This model revises that: the safety engine's actual output is
    a *gating* decision (hard_rejection) plus a structured list of individual
    checks and warnings, not a single Decimal. Forcing that into
    TokenScore.explanation would mean either fabricating placeholder values
    for the other eight categories (momentum, narrative, ...) for a token
    that gets hard-rejected before those engines ever run, or leaving
    hard-rejected tokens without any persisted safety record at all -- both
    wrong. TokenScore.safety_score remains the plain summary number, expected
    to be populated from the latest TokenSafetyCheck.score once the full
    scoring engine (Batch 8) runs; this table is the detailed, independently
    queryable record of *why*.
    """

    class RiskLevel(models.TextChoices):
        LOW = "LOW", "Low"
        MODERATE = "MODERATE", "Moderate"
        HIGH = "HIGH", "High"
        EXTREME = "EXTREME", "Extreme"

    token = models.ForeignKey(Token, on_delete=models.CASCADE, related_name="safety_checks")
    timestamp = models.DateTimeField(db_index=True)

    score = percentage_field(help_text="0-100, higher is safer")
    risk_level = models.CharField(max_length=10, choices=RiskLevel.choices, db_index=True)
    hard_rejection = models.BooleanField(default=False, db_index=True)
    hard_rejection_reasons = models.JSONField(default=list, blank=True)
    checks = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [models.Index(fields=["token", "-timestamp"])]

    def __str__(self) -> str:
        return f"{self.token} safety={self.score} ({self.risk_level}) @ {self.timestamp:%Y-%m-%d %H:%M}"

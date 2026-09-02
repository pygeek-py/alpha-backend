from django.db import models

from apps.core.fields import probability_field
from apps.core.models import TimestampedModel
from apps.tokens.models import Token


class Prediction(TimestampedModel):
    """A point-in-time 2x/3x/5x probability estimate for a token (PRD S25,
    S49). `model_version` is a free-text tag ("rule-v1" in V1; once ml.ModelVersion
    predictions exist in Batch 17+, its version string goes here too -- kept
    as a plain CharField rather than an FK so this app has no dependency on
    `ml` before ML actually exists).

    `feature_snapshot` is the reproducibility payload: every input value the
    prediction was computed from, captured at prediction time. This is also
    where current/target market cap and any other point-in-time context live,
    rather than as dedicated columns -- it's the single source of "what was
    known when," which is what data-leakage prevention (PRD S29) depends on.
    """

    token = models.ForeignKey(Token, on_delete=models.CASCADE, related_name="predictions")
    timestamp = models.DateTimeField(db_index=True)
    model_version = models.CharField(max_length=32, default="rule-v1")

    probability_2x = probability_field()
    probability_3x = probability_field()
    probability_5x = probability_field()
    risk_probability = probability_field(null=True, blank=True)

    expected_time_to_target = models.DurationField(null=True, blank=True)
    feature_snapshot = models.JSONField(default=dict)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [models.Index(fields=["token", "-timestamp"])]

    def __str__(self) -> str:
        return f"{self.token} 2x={self.probability_2x} @ {self.timestamp:%Y-%m-%d %H:%M}"

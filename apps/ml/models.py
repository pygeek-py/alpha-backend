from django.db import models

from apps.core.models import TimestampedModel


class TrainingDataset(TimestampedModel):
    """A versioned, chronologically-bounded slice of historical data used to
    train a model (PRD S52). `split_boundaries` records the train/val/test
    date cutoffs explicitly so a chronological (never shuffled) split is
    auditable after the fact, not just an assumption about how the pipeline
    behaved when it ran.
    """

    name = models.CharField(max_length=64, unique=True)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    row_count = models.PositiveIntegerField(null=True, blank=True)
    feature_set_version = models.CharField(max_length=32, blank=True)
    split_boundaries = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name


class ModelVersion(TimestampedModel):
    """A trained model's metadata and evaluation metrics (PRD S53). Only one
    ModelVersion per `name` should have is_deployed=True at a time -- enforced
    by the promotion logic in Batch 18, not a DB constraint, since "deploy"
    is a business decision (must beat the previous model) rather than a data
    integrity rule.
    """

    name = models.CharField(max_length=64, db_index=True, help_text='e.g. "2x_probability_classifier"')
    version = models.CharField(max_length=32, help_text='e.g. "v0.7"')

    training_dataset = models.ForeignKey(
        TrainingDataset, on_delete=models.SET_NULL, null=True, blank=True, related_name="model_versions"
    )
    trained_at = models.DateTimeField()
    feature_set = models.JSONField(default=list, blank=True)
    hyperparameters = models.JSONField(default=dict, blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    artifact_path = models.CharField(max_length=512, blank=True)

    is_deployed = models.BooleanField(default=False, db_index=True)
    deployed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-trained_at"]
        constraints = [
            models.UniqueConstraint(fields=["name", "version"], name="unique_model_name_version")
        ]

    def __str__(self) -> str:
        return f"{self.name} {self.version}"

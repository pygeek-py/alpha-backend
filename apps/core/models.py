from django.db import models


class TimestampedModel(models.Model):
    """Adds created_at/updated_at to any model that inherits it."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SourcedModel(TimestampedModel):
    """For any model populated from an external data provider. `is_mock` must
    never be left to infer from context -- every row states outright whether
    it's real provider data or fixture-backed mock data, per the project's
    "never make mock data look like production data" rule. `source` names
    which provider produced the row (e.g. "birdeye", "helius", "mock").
    """

    is_mock = models.BooleanField(default=False, db_index=True)
    source = models.CharField(max_length=32, default="mock")

    class Meta:
        abstract = True

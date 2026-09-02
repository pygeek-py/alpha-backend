import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.ml.models import ModelVersion, TrainingDataset


@pytest.mark.django_db
class TestTrainingDataset:
    def test_create(self):
        dataset = TrainingDataset.objects.create(
            name="dataset-2026-08-v1",
            start_date=timezone.now(),
            end_date=timezone.now(),
            split_boundaries={"train_end": "2026-06-01", "val_end": "2026-07-01"},
        )
        assert dataset.row_count is None


@pytest.mark.django_db
class TestModelVersion:
    def test_unique_name_version_pair(self):
        dataset = TrainingDataset.objects.create(
            name="ds1", start_date=timezone.now(), end_date=timezone.now()
        )
        ModelVersion.objects.create(
            name="2x_classifier", version="v0.1", training_dataset=dataset, trained_at=timezone.now()
        )
        with pytest.raises(IntegrityError):
            ModelVersion.objects.create(
                name="2x_classifier", version="v0.1", training_dataset=dataset, trained_at=timezone.now()
            )

    def test_defaults_not_deployed(self):
        model = ModelVersion.objects.create(name="3x_classifier", version="v0.1", trained_at=timezone.now())
        assert model.is_deployed is False
        assert model.deployed_at is None

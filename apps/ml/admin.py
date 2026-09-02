from django.contrib import admin

from apps.ml.models import ModelVersion, TrainingDataset


@admin.register(TrainingDataset)
class TrainingDatasetAdmin(admin.ModelAdmin):
    list_display = ("name", "start_date", "end_date", "row_count")


@admin.register(ModelVersion)
class ModelVersionAdmin(admin.ModelAdmin):
    list_display = ("name", "version", "trained_at", "is_deployed")
    list_filter = ("name", "is_deployed")

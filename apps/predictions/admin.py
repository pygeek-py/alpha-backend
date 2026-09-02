from django.contrib import admin

from apps.predictions.models import Prediction


@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display = (
        "token",
        "timestamp",
        "probability_2x",
        "probability_3x",
        "probability_5x",
        "model_version",
    )
    list_filter = ("model_version",)
    date_hierarchy = "timestamp"

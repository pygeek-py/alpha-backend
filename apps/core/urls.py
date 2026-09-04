from django.urls import path

from apps.core.views import HealthCheckView, OverviewStatsView, RunPipelineView

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health"),
    path("dashboard/overview/", OverviewStatsView.as_view(), name="dashboard-overview"),
    path("pipeline/run/", RunPipelineView.as_view(), name="pipeline-run"),
]

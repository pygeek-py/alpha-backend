from django.urls import path

from apps.core.views import HealthCheckView, OverviewStatsView

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health"),
    path("dashboard/overview/", OverviewStatsView.as_view(), name="dashboard-overview"),
]

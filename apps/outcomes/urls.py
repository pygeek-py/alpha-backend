from django.urls import path

from apps.outcomes.views import PerformanceView

urlpatterns = [
    path("performance/", PerformanceView.as_view(), name="outcomes-performance"),
]

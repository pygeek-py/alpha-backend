from django.urls import path

from apps.alerts.views import AlertListView

urlpatterns = [
    path("", AlertListView.as_view(), name="alerts-list"),
]

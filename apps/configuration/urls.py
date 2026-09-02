from django.urls import path

from apps.configuration.views import (
    ConfigurationApplyView,
    ConfigurationCurrentView,
    ConfigurationEvaluateView,
    ConfigurationHistoryView,
)

urlpatterns = [
    path("current/", ConfigurationCurrentView.as_view(), name="configuration-current"),
    path("evaluate/", ConfigurationEvaluateView.as_view(), name="configuration-evaluate"),
    path("apply/", ConfigurationApplyView.as_view(), name="configuration-apply"),
    path("history/", ConfigurationHistoryView.as_view(), name="configuration-history"),
]

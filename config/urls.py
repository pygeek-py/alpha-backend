from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.core.urls")),
    path("api/v1/telegram/", include("apps.telegram.urls")),
    path("api/v1/configuration/", include("apps.configuration.urls")),
    path("api/v1/tokens/", include("apps.tokens.urls")),
    path("api/v1/alerts/", include("apps.alerts.urls")),
    path("api/v1/outcomes/", include("apps.outcomes.urls")),
]

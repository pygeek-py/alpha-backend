from django.contrib import admin

from apps.alerts.models import Alert, AlertEvent


@admin.register(AlertEvent)
class AlertEventAdmin(admin.ModelAdmin):
    list_display = ("token", "from_state", "to_state", "score", "triggered_at")
    list_filter = ("to_state",)
    date_hierarchy = "triggered_at"


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ("token", "state", "score", "probability_2x", "telegram_sent", "created_at")
    list_filter = ("state", "telegram_sent", "is_priority")
    date_hierarchy = "created_at"

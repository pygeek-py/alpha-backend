from django.contrib import admin

from apps.configuration.models import ConfigurationChange, SystemConfiguration


@admin.register(SystemConfiguration)
class SystemConfigurationAdmin(admin.ModelAdmin):
    list_display = (
        "autonomy_mode",
        "min_opportunity_score",
        "max_alerts_per_hour",
        "is_active",
        "updated_at",
    )


@admin.register(ConfigurationChange)
class ConfigurationChangeAdmin(admin.ModelAdmin):
    list_display = ("change_source", "model_version", "created_at")
    list_filter = ("change_source",)
    date_hierarchy = "created_at"

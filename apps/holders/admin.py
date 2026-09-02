from django.contrib import admin

from apps.holders.models import HolderSnapshot


@admin.register(HolderSnapshot)
class HolderSnapshotAdmin(admin.ModelAdmin):
    list_display = ("token", "timestamp", "holder_count", "top_holder_pct", "is_mock")
    list_filter = ("is_mock",)
    date_hierarchy = "timestamp"

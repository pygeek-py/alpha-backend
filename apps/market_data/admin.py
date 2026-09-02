from django.contrib import admin

from apps.market_data.models import TokenSnapshot


@admin.register(TokenSnapshot)
class TokenSnapshotAdmin(admin.ModelAdmin):
    list_display = ("token", "timestamp", "price", "market_cap", "is_mock")
    list_filter = ("is_mock", "source")
    date_hierarchy = "timestamp"

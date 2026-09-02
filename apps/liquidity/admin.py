from django.contrib import admin

from apps.liquidity.models import LiquiditySnapshot


@admin.register(LiquiditySnapshot)
class LiquiditySnapshotAdmin(admin.ModelAdmin):
    list_display = ("token", "timestamp", "liquidity_usd", "lp_locked", "is_mock")
    list_filter = ("is_mock", "lp_locked", "lp_burned")
    date_hierarchy = "timestamp"

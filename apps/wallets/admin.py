from django.contrib import admin

from apps.wallets.models import Wallet, WalletCluster, WalletPerformance, WalletTransaction


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = (
        "address", "label", "classification", "classification_confidence", "cluster", "is_mock",
    )
    list_filter = ("classification", "is_mock", "cluster")
    search_fields = ("address", "label")


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ("wallet", "token", "side", "amount_usd", "occurred_at", "is_mock")
    list_filter = ("side", "is_mock")
    date_hierarchy = "occurred_at"


@admin.register(WalletPerformance)
class WalletPerformanceAdmin(admin.ModelAdmin):
    list_display = ("wallet", "reputation_score", "win_rate", "trade_count", "last_calculated_at")


@admin.register(WalletCluster)
class WalletClusterAdmin(admin.ModelAdmin):
    list_display = ("__str__", "shared_token_count", "confidence", "detected_at")
    date_hierarchy = "detected_at"

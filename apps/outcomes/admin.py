from django.contrib import admin

from apps.outcomes.models import TokenOutcome, TokenOutcomeSnapshot


class TokenOutcomeSnapshotInline(admin.TabularInline):
    model = TokenOutcomeSnapshot
    extra = 0


@admin.register(TokenOutcome)
class TokenOutcomeAdmin(admin.ModelAdmin):
    list_display = (
        "token",
        "reference_timestamp",
        "max_multiple",
        "reached_2x",
        "reached_3x",
        "tracking_complete",
    )
    list_filter = ("reached_2x", "reached_3x", "reached_5x", "tracking_complete")
    date_hierarchy = "reference_timestamp"
    inlines = [TokenOutcomeSnapshotInline]

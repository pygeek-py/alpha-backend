from django.contrib import admin

from apps.scoring.models import TokenSafetyCheck, TokenScore


@admin.register(TokenScore)
class TokenScoreAdmin(admin.ModelAdmin):
    list_display = (
        "token", "timestamp", "opportunity_score", "risk_score", "score_2x", "score_3x", "weights_version",
    )
    date_hierarchy = "timestamp"


@admin.register(TokenSafetyCheck)
class TokenSafetyCheckAdmin(admin.ModelAdmin):
    list_display = ("token", "timestamp", "score", "risk_level", "hard_rejection")
    list_filter = ("risk_level", "hard_rejection")
    date_hierarchy = "timestamp"

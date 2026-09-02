from django.contrib import admin

from apps.narratives.models import Narrative, TokenNarrative


@admin.register(Narrative)
class NarrativeAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "keywords", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("name",)


@admin.register(TokenNarrative)
class TokenNarrativeAdmin(admin.ModelAdmin):
    list_display = ("token", "narrative", "relevance_score", "strength_score", "momentum_score")
    list_filter = ("narrative",)

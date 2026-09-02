from django.contrib import admin

from apps.tokens.models import Token


@admin.register(Token)
class TokenAdmin(admin.ModelAdmin):
    list_display = ("symbol", "address", "is_active", "is_mock", "source", "created_at")
    list_filter = ("is_active", "is_mock", "source")
    search_fields = ("symbol", "name", "address", "creator_address")

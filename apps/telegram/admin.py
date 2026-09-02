from django.contrib import admin

from apps.telegram.models import TelegramConnection


@admin.register(TelegramConnection)
class TelegramConnectionAdmin(admin.ModelAdmin):
    list_display = ("user", "chat_id", "is_active", "last_test_success")

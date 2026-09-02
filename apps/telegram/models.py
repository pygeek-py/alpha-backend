from django.conf import settings
from django.db import models

from apps.core.models import TimestampedModel


class TelegramConnection(TimestampedModel):
    """A single operator's Telegram alert destination and preferences (PRD
    S38). The bot token itself is never stored here -- it's TELEGRAM_BOT_TOKEN
    in the environment, per the project's "never hardcode/store credentials
    in the database" security rule. This model only holds the destination
    chat and per-alert-type on/off switches.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="telegram_connection"
    )
    chat_id = models.CharField(max_length=64)
    is_active = models.BooleanField(default=True)

    notify_watch = models.BooleanField(default=False, help_text="Dashboard-only by default per PRD S36")
    notify_developing = models.BooleanField(default=False)
    notify_confirmed = models.BooleanField(default=True)
    notify_breakout = models.BooleanField(default=True)
    notify_invalidated = models.BooleanField(default=True)
    notify_priority = models.BooleanField(default=True)

    last_test_at = models.DateTimeField(null=True, blank=True)
    last_test_success = models.BooleanField(null=True, blank=True)

    def __str__(self) -> str:
        return f"Telegram connection for {self.user}"

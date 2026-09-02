from rest_framework import serializers

from apps.telegram.models import TelegramConnection


class TelegramConnectionSerializer(serializers.ModelSerializer):
    """PRD S38: the operator's Telegram connection and per-alert-type
    toggles. `last_test_at`/`last_test_success` are status the server
    manages (via /test/), never client-writable."""

    class Meta:
        model = TelegramConnection
        fields = [
            "chat_id",
            "is_active",
            "notify_watch",
            "notify_developing",
            "notify_confirmed",
            "notify_breakout",
            "notify_invalidated",
            "notify_priority",
            "last_test_at",
            "last_test_success",
        ]
        read_only_fields = ["last_test_at", "last_test_success"]


class DiscoveredChatSerializer(serializers.Serializer):
    chat_id = serializers.CharField()
    chat_type = serializers.CharField()
    name = serializers.CharField()

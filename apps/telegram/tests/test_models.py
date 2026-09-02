import pytest
from django.db import IntegrityError

from apps.telegram.models import TelegramConnection
from apps.users.factories import UserFactory


@pytest.mark.django_db
class TestTelegramConnection:
    def test_create_with_default_notification_prefs(self):
        user = UserFactory()
        conn = TelegramConnection.objects.create(user=user, chat_id="123456789")
        assert conn.notify_watch is False
        assert conn.notify_confirmed is True
        assert conn.notify_breakout is True

    def test_one_connection_per_user(self):
        user = UserFactory()
        TelegramConnection.objects.create(user=user, chat_id="1")
        with pytest.raises(IntegrityError):
            TelegramConnection.objects.create(user=user, chat_id="2")

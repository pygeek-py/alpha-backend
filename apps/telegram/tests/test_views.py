from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.telegram.client import DiscoveredChat, TelegramError, TelegramSendResult
from apps.telegram.models import TelegramConnection
from apps.users.factories import UserFactory


@pytest.fixture
def client_for():
    def _make(user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    return _make


@pytest.mark.django_db
class TestTelegramTestView:
    def test_requires_authentication(self):
        client = APIClient()
        response = client.post("/api/v1/telegram/test/")
        assert response.status_code == 401 or response.status_code == 403

    def test_no_connection_returns_400(self, client_for):
        user = UserFactory()
        response = client_for(user).post("/api/v1/telegram/test/")
        assert response.status_code == 400

    def test_no_chat_id_returns_400(self, client_for):
        user = UserFactory()
        TelegramConnection.objects.create(user=user, chat_id="")
        response = client_for(user).post("/api/v1/telegram/test/")
        assert response.status_code == 400

    def test_successful_test_returns_200(self, client_for):
        user = UserFactory()
        TelegramConnection.objects.create(user=user, chat_id="12345")
        with patch("apps.telegram.services.TelegramClient") as mock_client:
            mock_client.return_value.send_message.return_value = TelegramSendResult(message_id=1)
            response = client_for(user).post("/api/v1/telegram/test/")

        assert response.status_code == 200
        assert response.data["success"] is True

    def test_delivery_failure_returns_502(self, client_for):
        user = UserFactory()
        TelegramConnection.objects.create(user=user, chat_id="12345")
        with patch("apps.telegram.services.TelegramClient") as mock_client:
            mock_client.return_value.send_message.side_effect = TelegramError("bad chat id")
            response = client_for(user).post("/api/v1/telegram/test/")

        assert response.status_code == 502
        assert response.data["success"] is False

    def test_does_not_leak_another_users_connection(self, client_for):
        other_user = UserFactory()
        TelegramConnection.objects.create(user=other_user, chat_id="99999")
        me = UserFactory()
        response = client_for(me).post("/api/v1/telegram/test/")
        assert response.status_code == 400


@pytest.mark.django_db
class TestTelegramConnectionView:
    def test_requires_authentication(self):
        response = APIClient().get("/api/v1/telegram/connection/")
        assert response.status_code in (401, 403)

    def test_get_returns_null_when_no_connection_exists(self, client_for):
        response = client_for(UserFactory()).get("/api/v1/telegram/connection/")
        assert response.status_code == 200
        assert response.data is None

    def test_get_returns_the_users_own_connection(self, client_for):
        user = UserFactory()
        TelegramConnection.objects.create(user=user, chat_id="12345", notify_breakout=True)

        response = client_for(user).get("/api/v1/telegram/connection/")

        assert response.status_code == 200
        assert response.data["chat_id"] == "12345"
        assert response.data["notify_breakout"] is True

    def test_get_does_not_leak_another_users_connection(self, client_for):
        other_user = UserFactory()
        TelegramConnection.objects.create(user=other_user, chat_id="99999")

        response = client_for(UserFactory()).get("/api/v1/telegram/connection/")

        assert response.data is None

    def test_put_creates_a_new_connection(self, client_for):
        user = UserFactory()

        response = client_for(user).put(
            "/api/v1/telegram/connection/", {"chat_id": "6591991724", "notify_confirmed": True}, format="json"
        )

        assert response.status_code == 200
        assert response.data["chat_id"] == "6591991724"
        assert TelegramConnection.objects.get(user=user).chat_id == "6591991724"

    def test_put_updates_the_existing_connection(self, client_for):
        user = UserFactory()
        TelegramConnection.objects.create(user=user, chat_id="old-id")

        response = client_for(user).put(
            "/api/v1/telegram/connection/", {"chat_id": "new-id"}, format="json"
        )

        assert response.status_code == 200
        assert response.data["chat_id"] == "new-id"
        assert TelegramConnection.objects.filter(user=user).count() == 1

    def test_put_cannot_set_last_test_fields(self, client_for):
        user = UserFactory()

        response = client_for(user).put(
            "/api/v1/telegram/connection/",
            {"chat_id": "123", "last_test_success": True},
            format="json",
        )

        assert response.status_code == 200
        assert TelegramConnection.objects.get(user=user).last_test_success is None

    def test_put_missing_chat_id_returns_400(self, client_for):
        response = client_for(UserFactory()).put(
            "/api/v1/telegram/connection/", {}, format="json"
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestTelegramDiscoverChatsView:
    def test_requires_authentication(self):
        response = APIClient().get("/api/v1/telegram/discover-chats/")
        assert response.status_code in (401, 403)

    def test_returns_discovered_chats(self, client_for):
        with patch("apps.telegram.views.TelegramClient") as mock_client:
            mock_client.return_value.get_updates.return_value = [
                DiscoveredChat(chat_id="6591991724", chat_type="private", name="pygeek_py")
            ]
            response = client_for(UserFactory()).get("/api/v1/telegram/discover-chats/")

        assert response.status_code == 200
        assert response.data == [
            {"chat_id": "6591991724", "chat_type": "private", "name": "pygeek_py"}
        ]

    def test_telegram_error_returns_502(self, client_for):
        with patch("apps.telegram.views.TelegramClient") as mock_client:
            mock_client.return_value.get_updates.side_effect = TelegramError("bad token")
            response = client_for(UserFactory()).get("/api/v1/telegram/discover-chats/")

        assert response.status_code == 502

from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.alerts.models import Alert, AlertState
from apps.tokens.factories import TokenFactory
from apps.users.factories import UserFactory


@pytest.fixture
def client():
    api_client = APIClient()
    api_client.force_authenticate(user=UserFactory())
    return api_client


@pytest.mark.django_db
class TestAlertListView:
    def test_requires_authentication(self):
        response = APIClient().get(reverse("alerts-list"))
        assert response.status_code in (401, 403)

    def test_empty_list(self, client):
        response = client.get(reverse("alerts-list"))
        assert response.status_code == 200
        assert response.json() == []

    def test_returns_alerts_newest_first(self, client):
        token = TokenFactory(symbol="PEPE")
        Alert.objects.create(token=token, state=AlertState.WATCHING, score=Decimal("50"))
        Alert.objects.create(token=token, state=AlertState.CONFIRMED, score=Decimal("80"))

        response = client.get(reverse("alerts-list"))

        body = response.json()
        assert len(body) == 2
        assert body[0]["state"] == AlertState.CONFIRMED
        assert body[0]["token_symbol"] == "PEPE"

    def test_state_filter(self, client):
        token = TokenFactory()
        Alert.objects.create(token=token, state=AlertState.WATCHING, score=Decimal("50"))
        Alert.objects.create(token=token, state=AlertState.CONFIRMED, score=Decimal("80"))

        response = client.get(reverse("alerts-list"), {"state": "confirmed"})

        body = response.json()
        assert len(body) == 1
        assert body[0]["state"] == AlertState.CONFIRMED

    def test_priority_only_filter(self, client):
        token = TokenFactory()
        Alert.objects.create(token=token, state=AlertState.CONFIRMED, score=Decimal("80"), is_priority=False)
        Alert.objects.create(token=token, state=AlertState.CONFIRMED, score=Decimal("97"), is_priority=True)

        response = client.get(reverse("alerts-list"), {"priority_only": "true"})

        body = response.json()
        assert len(body) == 1
        assert body[0]["is_priority"] is True

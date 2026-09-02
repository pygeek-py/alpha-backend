from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.alerts.models import Alert, AlertState
from apps.outcomes.models import TokenOutcome
from apps.tokens.factories import TokenFactory
from apps.users.factories import UserFactory


@pytest.fixture
def client():
    api_client = APIClient()
    api_client.force_authenticate(user=UserFactory())
    return api_client


@pytest.mark.django_db
class TestPerformanceView:
    def test_requires_authentication(self):
        response = APIClient().get(reverse("outcomes-performance"))
        assert response.status_code in (401, 403)

    def test_empty_report(self, client):
        response = client.get(reverse("outcomes-performance"))

        assert response.status_code == 200
        body = response.json()
        assert body["summary"]["total_signals"] == 0
        assert body["summary"]["hit_rate_2x_pct"] is None
        assert body["by_narrative"] == []

    def test_report_reflects_real_outcomes(self, client):
        token = TokenFactory()
        alert = Alert.objects.create(token=token, state=AlertState.CONFIRMED, score=Decimal("80"))
        TokenOutcome.objects.create(
            token=token, alert=alert, reference_timestamp=timezone.now(), initial_price="1",
            reached_2x=True, reached_3x=False, max_multiple=Decimal("2.4"), tracking_complete=True,
        )

        response = client.get(reverse("outcomes-performance"))

        body = response.json()
        assert body["summary"]["total_signals"] == 1
        assert body["summary"]["hit_rate_2x_pct"] == "100.00"

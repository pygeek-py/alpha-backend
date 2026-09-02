import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.users.factories import UserFactory


@pytest.mark.django_db
class TestOverviewStatsView:
    def test_requires_authentication(self):
        client = APIClient()
        response = client.get(reverse("dashboard-overview"))
        assert response.status_code in (401, 403)

    def test_authenticated_request_returns_stats(self):
        client = APIClient()
        client.force_authenticate(user=UserFactory())

        response = client.get(reverse("dashboard-overview"))

        assert response.status_code == 200
        body = response.json()
        for key in (
            "tokens_scanned_today", "candidates", "watchlist", "confirmed",
            "breakouts", "invalidated", "alerts_sent", "hit_rate_2x_pct", "hit_rate_3x_pct",
        ):
            assert key in body

from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.configuration.models import ConfigurationChange, ConfigurationChangeSource
from apps.configuration.services import apply_configuration_change, get_current_configuration
from apps.users.factories import UserFactory


@pytest.fixture
def client():
    api_client = APIClient()
    api_client.force_authenticate(user=UserFactory())
    return api_client


@pytest.mark.django_db
class TestConfigurationCurrentView:
    def test_requires_authentication(self):
        response = APIClient().get(reverse("configuration-current"))
        assert response.status_code in (401, 403)

    def test_returns_current_config_and_recommendation(self, client):
        response = client.get(reverse("configuration-current"))

        assert response.status_code == 200
        body = response.json()
        assert "current" in body
        assert "recommendation" in body
        assert body["current"]["autonomy_mode"] == "ai_automatic"
        assert "thresholds" in body["recommendation"]
        assert "min_opportunity_score" in body["recommendation"]["thresholds"]

    def test_patch_updates_autonomy_mode(self, client):
        response = client.patch(reverse("configuration-current"), {"autonomy_mode": "manual"})

        assert response.status_code == 200
        assert response.json()["autonomy_mode"] == "manual"
        assert get_current_configuration().autonomy_mode == "manual"

    def test_patch_rejects_invalid_autonomy_mode(self, client):
        response = client.patch(reverse("configuration-current"), {"autonomy_mode": "bogus"})
        assert response.status_code == 400


@pytest.mark.django_db
class TestConfigurationEvaluateView:
    def test_requires_authentication(self):
        response = APIClient().post(reverse("configuration-evaluate"), {}, format="json")
        assert response.status_code in (401, 403)

    def test_evaluates_a_proposed_change_without_applying_it(self, client):
        response = client.post(
            reverse("configuration-evaluate"), {"min_opportunity_score": "70"}, format="json"
        )

        assert response.status_code == 200
        body = response.json()
        assert "assessment" in body
        assert "simulation_current" in body
        assert "simulation_proposed" in body
        assert 0 <= float(body["assessment"]["recommendation_score"]) <= 100
        # Nothing applied -- config unchanged.
        assert get_current_configuration().min_opportunity_score == Decimal("0.00")

    def test_invalid_value_returns_400(self, client):
        response = client.post(
            reverse("configuration-evaluate"), {"min_opportunity_score": "not-a-number"}, format="json"
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestConfigurationApplyView:
    def test_requires_authentication(self):
        response = APIClient().post(reverse("configuration-apply"), {}, format="json")
        assert response.status_code in (401, 403)

    def test_applies_and_records_the_change(self, client):
        response = client.post(
            reverse("configuration-apply"),
            {"min_opportunity_score": "75", "reason": "testing via API"},
            format="json",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["current"]["min_opportunity_score"] == "75.00"
        assert body["change"]["reason"] == "testing via API"
        assert body["change"]["change_source"] == "manual"
        assert get_current_configuration().min_opportunity_score == Decimal("75.00")


@pytest.mark.django_db
class TestConfigurationHistoryView:
    def test_requires_authentication(self):
        response = APIClient().get(reverse("configuration-history"))
        assert response.status_code in (401, 403)

    def test_lists_past_changes_newest_first(self, client):
        apply_configuration_change(
            {"min_opportunity_score": Decimal("60")},
            source=ConfigurationChangeSource.MANUAL,
            reason="first",
        )
        apply_configuration_change(
            {"min_opportunity_score": Decimal("70")},
            source=ConfigurationChangeSource.MANUAL,
            reason="second",
        )

        response = client.get(reverse("configuration-history"))

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 2
        assert body[0]["reason"] == "second"
        assert ConfigurationChange.objects.count() == 2

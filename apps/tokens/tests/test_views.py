from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.alerts.models import AlertEvent, AlertState
from apps.scoring.models import TokenScore
from apps.tokens.factories import TokenFactory
from apps.users.factories import UserFactory


@pytest.fixture
def client():
    api_client = APIClient()
    api_client.force_authenticate(user=UserFactory())
    return api_client


def _scored_token(opportunity_score):
    token = TokenFactory()
    TokenScore.objects.create(
        token=token, timestamp=timezone.now(), opportunity_score=opportunity_score,
        risk_score=Decimal("20"), score_2x=opportunity_score, score_3x=opportunity_score,
    )
    return token


@pytest.mark.django_db
class TestLiveFeedView:
    def test_requires_authentication(self):
        response = APIClient().get(reverse("tokens-live-feed"))
        assert response.status_code in (401, 403)

    def test_returns_a_row_per_active_token(self, client):
        _scored_token(Decimal("50"))
        _scored_token(Decimal("80"))

        response = client.get(reverse("tokens-live-feed"))

        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_default_ordering_is_by_opportunity_score_descending(self, client):
        _scored_token(Decimal("30"))
        _scored_token(Decimal("90"))

        response = client.get(reverse("tokens-live-feed"))

        scores = [row["opportunity_score"] for row in response.json()]
        assert scores == ["90.00", "30.00"]

    def test_ordering_query_param_is_respected(self, client):
        _scored_token(Decimal("30"))
        _scored_token(Decimal("90"))

        response = client.get(reverse("tokens-live-feed"), {"ordering": "opportunity_score"})

        scores = [row["opportunity_score"] for row in response.json()]
        assert scores == ["30.00", "90.00"]

    def test_state_query_param_filters(self, client):
        watching = _scored_token(Decimal("50"))
        AlertEvent.objects.create(
            token=watching, to_state=AlertState.WATCHING, triggered_at=timezone.now()
        )
        _scored_token(Decimal("60"))  # stays "discovered"

        response = client.get(reverse("tokens-live-feed"), {"state": "watching"})

        body = response.json()
        assert len(body) == 1
        assert body[0]["token_id"] == watching.id


@pytest.mark.django_db
class TestTokenDetailView:
    def test_requires_authentication(self):
        token = TokenFactory()
        response = APIClient().get(reverse("tokens-detail", args=[token.id]))
        assert response.status_code in (401, 403)

    def test_unknown_token_returns_404(self, client):
        response = client.get(reverse("tokens-detail", args=[999999]))
        assert response.status_code == 404

    def test_returns_the_full_payload_shape(self, client):
        token = _scored_token(Decimal("70"))
        response = client.get(reverse("tokens-detail", args=[token.id]))

        assert response.status_code == 200
        body = response.json()
        assert body["overview"]["token_id"] == token.id
        assert body["score"]["opportunity_score"] == "70.00"
        assert body["narratives"] == []
        assert body["outcome"] is None
        assert body["wallet_activity"] == []


@pytest.mark.django_db
class TestTokenHistoryView:
    def test_requires_authentication(self):
        token = TokenFactory()
        response = APIClient().get(reverse("tokens-history", args=[token.id]))
        assert response.status_code in (401, 403)

    def test_unknown_token_returns_404(self, client):
        response = client.get(reverse("tokens-history", args=[999999]))
        assert response.status_code == 404

    def test_returns_empty_history_for_a_fresh_token(self, client):
        token = TokenFactory()
        response = client.get(reverse("tokens-history", args=[token.id]))

        assert response.status_code == 200
        assert response.json() == {"price": [], "holders": []}

    def test_invalid_hours_param_falls_back_to_default(self, client):
        token = TokenFactory()
        response = client.get(reverse("tokens-history", args=[token.id]), {"hours": "not-a-number"})
        assert response.status_code == 200

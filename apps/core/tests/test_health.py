from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework.test import APIClient


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
def test_health_ok_when_db_and_redis_available(client):
    """DB is SQLite and cache is LocMemCache under test settings, so both
    are genuinely exercised; Celery is mocked since a broker isn't assumed."""
    with patch("apps.core.views._check_celery", return_value={"status": "unavailable", "workers": 0}):
        response = client.get(reverse("health"))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"]["status"] == "ok"
    assert body["checks"]["redis"]["status"] == "ok"
    assert body["checks"]["celery"]["status"] == "unavailable"


@pytest.mark.django_db
def test_health_degraded_when_database_fails(client):
    with patch("apps.core.views._check_database", return_value={"status": "error", "detail": "boom"}):
        response = client.get(reverse("health"))

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


@pytest.mark.django_db
def test_health_ok_when_celery_worker_responds(client):
    mock_result = {"status": "ok", "workers": 1, "latency_ms": 5.0}
    with patch("apps.core.views._check_celery", return_value=mock_result):
        response = client.get(reverse("health"))

    assert response.status_code == 200
    assert response.json()["checks"]["celery"]["status"] == "ok"


@pytest.mark.django_db
def test_health_endpoint_does_not_require_authentication(client):
    """The health endpoint must stay reachable by infra/monitoring without a token."""
    with patch("apps.core.views._check_celery", return_value={"status": "unavailable"}):
        response = client.get(reverse("health"))

    assert response.status_code in (200, 503)

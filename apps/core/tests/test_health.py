import time
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.pipeline import PIPELINE_LOOP_HEARTBEAT_CACHE_KEY


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


@pytest.mark.django_db
def test_pipeline_loop_reports_disabled_by_default(client, settings):
    """PIPELINE_INPROCESS_LOOP_ENABLED is off in every settings module
    except an actual live free-tier deployment (set via env var) -- confirm
    the health check reflects that rather than claiming the loop is
    running when it was never started."""
    settings.PIPELINE_INPROCESS_LOOP_ENABLED = False
    with patch("apps.core.views._check_celery", return_value={"status": "unavailable"}):
        response = client.get(reverse("health"))

    assert response.json()["checks"]["pipeline_loop"] == {"status": "disabled"}


@pytest.mark.django_db
def test_pipeline_loop_reports_not_started_when_enabled_with_no_heartbeat_yet(client, settings):
    settings.PIPELINE_INPROCESS_LOOP_ENABLED = True
    cache.delete(PIPELINE_LOOP_HEARTBEAT_CACHE_KEY)
    with patch("apps.core.views._check_celery", return_value={"status": "unavailable"}):
        response = client.get(reverse("health"))

    assert response.json()["checks"]["pipeline_loop"] == {"status": "not_started"}


@pytest.mark.django_db
def test_pipeline_loop_reports_ok_with_a_recent_heartbeat(client, settings):
    settings.PIPELINE_INPROCESS_LOOP_ENABLED = True
    cache.set(
        PIPELINE_LOOP_HEARTBEAT_CACHE_KEY,
        {"stage": "collect_market_data", "outcome": "ok", "at": time.time()},
        timeout=None,
    )
    with patch("apps.core.views._check_celery", return_value={"status": "unavailable"}):
        response = client.get(reverse("health"))

    loop_check = response.json()["checks"]["pipeline_loop"]
    assert loop_check["status"] == "ok"
    assert loop_check["last_stage"] == "collect_market_data"


@pytest.mark.django_db
def test_pipeline_loop_reports_stale_with_an_old_heartbeat(client, settings):
    settings.PIPELINE_INPROCESS_LOOP_ENABLED = True
    cache.set(
        PIPELINE_LOOP_HEARTBEAT_CACHE_KEY,
        {"stage": "discover_tokens", "outcome": "ok", "at": time.time() - 600},
        timeout=None,
    )
    with patch("apps.core.views._check_celery", return_value={"status": "unavailable"}):
        response = client.get(reverse("health"))

    assert response.json()["checks"]["pipeline_loop"]["status"] == "stale"

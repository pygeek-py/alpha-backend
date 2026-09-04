import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.users.factories import UserFactory


# transaction=True -- see apps/core/tests/test_pipeline.py's comment;
# this view also runs run_pipeline_once()'s real background-thread writes.
@pytest.mark.django_db(transaction=True)
class TestRunPipelineView:
    def test_requires_authentication(self):
        client = APIClient()
        response = client.post(reverse("pipeline-run"))
        assert response.status_code in (401, 403)

    def test_authenticated_request_runs_the_pipeline(self):
        client = APIClient()
        client.force_authenticate(user=UserFactory())

        response = client.post(reverse("pipeline-run"))

        assert response.status_code == 200
        body = response.json()
        assert "discover_tokens" in body
        assert "evaluate_ai_configuration" in body

    def test_get_is_not_allowed(self):
        client = APIClient()
        client.force_authenticate(user=UserFactory())

        response = client.get(reverse("pipeline-run"))

        assert response.status_code == 405

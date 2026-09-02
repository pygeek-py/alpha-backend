import pytest

from apps.tokens.models import Token
from apps.tokens.tasks import discover_tokens


@pytest.mark.django_db
def test_discover_tokens_task_creates_tokens():
    """CELERY_TASK_ALWAYS_EAGER (test settings) runs this synchronously, no
    broker/worker needed."""
    result = discover_tokens.delay(limit=3)
    assert result.get()["discovered"] == 3
    assert Token.objects.count() == 3

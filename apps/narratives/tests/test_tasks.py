
import pytest

from apps.narratives.factories import NarrativeFactory
from apps.narratives.models import TokenNarrative
from apps.narratives.tasks import (
    analyze_narrative,
    analyze_narrative_for_active_tokens,
    refresh_narrative_metrics_for_active_narratives,
)
from apps.tokens.factories import TokenFactory


@pytest.mark.django_db
def test_analyze_narrative_task_creates_links():
    NarrativeFactory(keywords=["zyxquartz"])
    token = TokenFactory(name="Zyxquartz Coin", symbol="ZXC")

    result = analyze_narrative.delay(token.id)

    assert result.get()["narratives_matched"] == 1
    assert TokenNarrative.objects.filter(token=token).exists()


@pytest.mark.django_db
def test_fan_out_queues_all_active_tokens():
    TokenFactory.create_batch(3)
    TokenFactory(is_active=False)

    result = analyze_narrative_for_active_tokens.delay()

    assert result.get()["queued"] == 3


@pytest.mark.django_db
def test_refresh_metrics_task_processes_active_narratives():
    from apps.narratives.models import Narrative

    NarrativeFactory()
    NarrativeFactory(is_active=False)
    active_count_before = Narrative.objects.filter(is_active=True).count()

    result = refresh_narrative_metrics_for_active_narratives.delay()

    # Includes any seed narratives too -- just confirm it processed exactly
    # the active set, not more, not fewer.
    assert result.get()["refreshed"] == active_count_before

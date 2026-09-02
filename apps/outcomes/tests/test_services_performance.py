from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.alerts.models import Alert, AlertState
from apps.narratives.factories import NarrativeFactory
from apps.narratives.models import TokenNarrative
from apps.outcomes.models import TokenOutcome
from apps.outcomes.services import get_performance_report
from apps.tokens.factories import TokenFactory


def _outcome(*, reached_2x=False, reached_3x=False, tracking_complete=True, score=Decimal("70"), token=None):
    token = token or TokenFactory()
    alert = Alert.objects.create(token=token, state=AlertState.CONFIRMED, score=score)
    return TokenOutcome.objects.create(
        token=token,
        alert=alert,
        reference_timestamp=timezone.now(),
        initial_price="1",
        reached_2x=reached_2x,
        reached_3x=reached_3x,
        tracking_complete=tracking_complete,
        max_multiple=Decimal("2.5") if reached_2x else Decimal("1.2"),
    )


@pytest.mark.django_db
class TestGetPerformanceReport:
    def test_no_outcomes_gives_honest_empty_report(self):
        report = get_performance_report()

        assert report["summary"].total_signals == 0
        assert report["summary"].hit_rate_2x_pct is None
        assert report["by_narrative"] == []
        assert report["by_age"] == []
        assert report["by_score"] == []

    def test_summary_reflects_real_outcomes(self):
        _outcome(reached_2x=True, reached_3x=True)
        _outcome(reached_2x=True, reached_3x=False)
        _outcome(reached_2x=False, reached_3x=False)

        report = get_performance_report()

        assert report["summary"].total_signals == 3
        assert report["summary"].completed_signals == 3
        assert report["summary"].hit_rate_2x_pct == Decimal("66.67")

    def test_narrative_breakdown_uses_the_tokens_top_narrative(self):
        token = TokenFactory()
        narrative = NarrativeFactory(name="AI Meme")
        TokenNarrative.objects.create(
            token=token, narrative=narrative, relevance_score=Decimal("90"), detected_at=timezone.now()
        )
        _outcome(token=token, reached_2x=True)

        report = get_performance_report()

        assert report["by_narrative"][0].label == "AI Meme"

    def test_age_breakdown_derives_from_token_launch_time(self):
        token = TokenFactory(launched_at=timezone.now() - timedelta(hours=5))
        _outcome(token=token)

        report = get_performance_report()

        assert report["by_age"][0].label == "3h+"

    def test_score_breakdown_uses_the_alerts_score(self):
        _outcome(score=Decimal("15"))

        report = get_performance_report()

        assert report["by_score"][0].label == "0-20"

    def test_incomplete_tracking_still_counted_in_total_but_not_rates(self):
        _outcome(tracking_complete=False, reached_2x=True)

        report = get_performance_report()

        assert report["summary"].total_signals == 1
        assert report["summary"].completed_signals == 0
        assert report["summary"].hit_rate_2x_pct is None

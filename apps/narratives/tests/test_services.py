from decimal import Decimal

import pytest
from django.utils import timezone

from apps.market_data.models import TokenSnapshot
from apps.narratives.factories import NarrativeFactory
from apps.narratives.models import TokenNarrative
from apps.narratives.services import (
    detect_token_narratives,
    get_narrative_competition,
    rank_tokens_in_narrative,
    refresh_narrative_metrics,
)
from apps.tokens.factories import TokenFactory


@pytest.mark.django_db
class TestDetectTokenNarratives:
    """Uses deliberately distinctive keywords/names (not "ai", "gaming",
    etc.) that won't collide with the seed narratives created by the
    narratives.0003_seed_narratives data migration, which also runs against
    the test database -- these tests need to reason about exactly which
    narratives matched, so accidental overlap with real seed keywords would
    make them unreliable."""

    def test_creates_link_for_matching_narrative(self):
        narrative = NarrativeFactory(keywords=["zyxquartz", "vorptide"])
        token = TokenFactory(name="Zyxquartz Vorptide Coin", symbol="ZVC")

        detect_token_narratives(token)

        link = TokenNarrative.objects.get(token=token, narrative=narrative)
        assert link.relevance_score == Decimal("70")  # 2 keywords * 35

    def test_no_match_creates_no_link(self):
        narrative = NarrativeFactory(keywords=["zyxquartz", "vorptide"])
        token = TokenFactory(name="Zephyr Lattice Coin", symbol="ZLC")

        detect_token_narratives(token)

        assert not TokenNarrative.objects.filter(token=token, narrative=narrative).exists()

    def test_inactive_narratives_are_ignored(self):
        narrative = NarrativeFactory(keywords=["zyxquartz"], is_active=False)
        token = TokenFactory(name="Zyxquartz Coin", symbol="ZXC")

        detect_token_narratives(token)

        assert not TokenNarrative.objects.filter(token=token, narrative=narrative).exists()

    def test_rerunning_updates_relevance_in_place_not_duplicating(self):
        narrative = NarrativeFactory(name="Zyxquartz Theme", keywords=["zyxquartz"])
        token = TokenFactory(name="Zyxquartz Coin", symbol="ZXC")

        detect_token_narratives(token)
        detect_token_narratives(token)

        assert TokenNarrative.objects.filter(token=token, narrative=narrative).count() == 1


@pytest.mark.django_db
class TestRefreshNarrativeMetrics:
    def test_computes_strength_from_linked_tokens_activity(self):
        narrative = NarrativeFactory()
        token = TokenFactory()
        TokenNarrative.objects.create(
            token=token, narrative=narrative, relevance_score=Decimal("80"), detected_at=timezone.now()
        )
        TokenSnapshot.objects.create(
            token=token, timestamp=timezone.now(), price=Decimal("0.01"),
            market_cap=Decimal("2500000"), volume_5m=Decimal("50000"),
        )

        result = refresh_narrative_metrics(narrative)

        assert result["active_token_count"] == 1
        assert result["strength_score"] is not None

        link = TokenNarrative.objects.get(token=token, narrative=narrative)
        assert link.strength_score == result["strength_score"]

    def test_second_run_computes_momentum_against_first(self):
        narrative = NarrativeFactory()
        token = TokenFactory()
        TokenNarrative.objects.create(
            token=token, narrative=narrative, relevance_score=Decimal("80"), detected_at=timezone.now()
        )
        TokenSnapshot.objects.create(
            token=token, timestamp=timezone.now(), price=Decimal("0.01"), market_cap=Decimal("1000000")
        )

        first = refresh_narrative_metrics(narrative)
        assert first["momentum_score"] is None  # no prior observation yet

        second = refresh_narrative_metrics(narrative)
        assert second["momentum_score"] is not None

    def test_no_linked_tokens_gives_zero_strength(self):
        narrative = NarrativeFactory()
        result = refresh_narrative_metrics(narrative)
        assert result["active_token_count"] == 0
        assert result["strength_score"] == Decimal("0.00")

    def test_inactive_tokens_are_excluded_from_activity(self):
        narrative = NarrativeFactory()
        token = TokenFactory(is_active=False)
        TokenNarrative.objects.create(
            token=token, narrative=narrative, relevance_score=Decimal("80"), detected_at=timezone.now()
        )
        result = refresh_narrative_metrics(narrative)
        assert result["active_token_count"] == 0


@pytest.mark.django_db
class TestRankTokensInNarrative:
    def test_orders_by_relevance_descending(self):
        narrative = NarrativeFactory()
        low = TokenFactory()
        high = TokenFactory()
        TokenNarrative.objects.create(
            token=low, narrative=narrative, relevance_score=Decimal("40"), detected_at=timezone.now()
        )
        TokenNarrative.objects.create(
            token=high, narrative=narrative, relevance_score=Decimal("90"), detected_at=timezone.now()
        )

        ranked = rank_tokens_in_narrative(narrative)

        assert [link.token for link in ranked] == [high, low]

    def test_excludes_inactive_tokens(self):
        narrative = NarrativeFactory()
        inactive = TokenFactory(is_active=False)
        TokenNarrative.objects.create(
            token=inactive, narrative=narrative, relevance_score=Decimal("90"), detected_at=timezone.now()
        )
        assert rank_tokens_in_narrative(narrative) == []


@pytest.mark.django_db
class TestSocialBlendingIsOptIn:
    def test_default_provider_does_not_blend_social_data(self):
        """SOCIAL_DATA_PROVIDER defaults to "none" -- confirms strength
        stays purely on-chain unless a real signal is explicitly opted in."""
        narrative = NarrativeFactory()
        token = TokenFactory()
        TokenNarrative.objects.create(
            token=token, narrative=narrative, relevance_score=Decimal("80"), detected_at=timezone.now()
        )
        result = refresh_narrative_metrics(narrative)
        # active_token_count=1, no market data -> token component only: 40*1/20=2
        assert result["strength_score"] == Decimal("2.00")

    def test_mock_provider_blends_when_explicitly_configured(self):
        from django.test import override_settings

        from providers.registry import get_social_data_provider

        narrative = NarrativeFactory()
        token = TokenFactory()
        TokenNarrative.objects.create(
            token=token, narrative=narrative, relevance_score=Decimal("80"), detected_at=timezone.now()
        )

        get_social_data_provider.cache_clear()
        try:
            with override_settings(SOCIAL_DATA_PROVIDER="mock"):
                result = refresh_narrative_metrics(narrative)
        finally:
            get_social_data_provider.cache_clear()

        # Blended with mock social data, the score should no longer be the
        # pure on-chain value of 2.00 -- proving the extension point works.
        assert result["strength_score"] != Decimal("2.00")


@pytest.mark.django_db
class TestGetNarrativeCompetition:
    def test_counts_active_linked_tokens(self):
        narrative = NarrativeFactory()
        for _ in range(3):
            TokenNarrative.objects.create(
                token=TokenFactory(), narrative=narrative, relevance_score=Decimal("50"),
                detected_at=timezone.now(),
            )
        result = get_narrative_competition(narrative)
        assert result.active_token_count == 3
        assert result.label == "low"

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.narratives.factories import NarrativeFactory
from apps.narratives.models import TokenNarrative
from apps.tokens.factories import TokenFactory


@pytest.mark.django_db
class TestNarrative:
    def test_name_unique(self):
        NarrativeFactory(name="AI Meme")
        with pytest.raises(IntegrityError):
            NarrativeFactory(name="AI Meme")

    def test_category_is_free_text_not_restricted_choices(self):
        # A category outside the suggested seed list must still be allowed --
        # the PRD explicitly requires this to stay extensible.
        narrative = NarrativeFactory(category="brand_new_trend_nobody_anticipated")
        assert narrative.category == "brand_new_trend_nobody_anticipated"


@pytest.mark.django_db
class TestTokenNarrative:
    def test_unique_token_narrative_pair(self):
        token = TokenFactory()
        narrative = NarrativeFactory()
        TokenNarrative.objects.create(token=token, narrative=narrative, detected_at=timezone.now())
        with pytest.raises(IntegrityError):
            TokenNarrative.objects.create(token=token, narrative=narrative, detected_at=timezone.now())

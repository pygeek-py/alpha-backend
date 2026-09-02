import pytest
from django.utils import timezone

from apps.scoring.models import TokenScore
from apps.tokens.factories import TokenFactory


@pytest.mark.django_db
class TestTokenScore:
    def test_create_with_explanation(self):
        token = TokenFactory()
        score = TokenScore.objects.create(
            token=token,
            timestamp=timezone.now(),
            safety_score="91", liquidity_score="84", momentum_score="92",
            holder_growth_score="87", wallet_score="89", buy_pressure_score="83",
            price_structure_score="81", narrative_score="94", creator_score="88",
            opportunity_score="89", risk_score="17",
            explanation={"positive": ["Volume acceleration"], "negative": [], "missing": []},
        )
        assert token.scores.get() == score
        assert score.explanation["positive"] == ["Volume acceleration"]
        assert score.weights_version == "v1"

import pytest

from apps.predictions.factories import PredictionFactory


@pytest.mark.django_db
class TestPrediction:
    def test_create_with_feature_snapshot(self):
        prediction = PredictionFactory(feature_snapshot={"opportunity_score": 89, "liquidity_usd": 75000})
        assert prediction.model_version == "rule-v1"
        assert prediction.feature_snapshot["opportunity_score"] == 89

    def test_related_name_from_token(self):
        prediction = PredictionFactory()
        assert prediction.token.predictions.get() == prediction

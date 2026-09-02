import factory
from django.utils import timezone

from apps.predictions.models import Prediction
from apps.tokens.factories import TokenFactory


class PredictionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Prediction

    token = factory.SubFactory(TokenFactory)
    timestamp = factory.LazyFunction(timezone.now)
    probability_2x = "0.5000"
    probability_3x = "0.3000"
    probability_5x = "0.1000"

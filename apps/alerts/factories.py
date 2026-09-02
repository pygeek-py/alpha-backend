import factory
from django.utils import timezone

from apps.alerts.models import Alert, AlertEvent, AlertState
from apps.tokens.factories import TokenFactory


class AlertEventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AlertEvent

    token = factory.SubFactory(TokenFactory)
    to_state = AlertState.WATCHING
    triggered_at = factory.LazyFunction(timezone.now)


class AlertFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Alert

    token = factory.SubFactory(TokenFactory)
    state = AlertState.CONFIRMED

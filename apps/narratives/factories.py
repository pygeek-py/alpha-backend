import factory

from apps.narratives.models import Narrative


class NarrativeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Narrative

    name = factory.Sequence(lambda n: f"Narrative {n}")
    category = "ai"

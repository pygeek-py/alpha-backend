import factory

from apps.tokens.models import Token


class TokenFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Token

    address = factory.Sequence(lambda n: f"MockMint{n:040d}")
    symbol = factory.Sequence(lambda n: f"TOK{n}")
    name = factory.Faker("word")
    is_mock = True
    source = "mock"

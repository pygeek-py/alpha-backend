import factory

from apps.wallets.models import Wallet


class WalletFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Wallet

    address = factory.Sequence(lambda n: f"MockWallet{n:040d}")
    is_mock = True
    source = "mock"

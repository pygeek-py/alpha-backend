"""Shared DecimalField presets so precision/scale stays consistent across
every app instead of each model picking its own max_digits/decimal_places.

Memecoin unit prices routinely have many leading zeros (e.g. $0.0000000234),
which is why price_field is far wider than usd_field.
"""

from django.db import models


def usd_field(**kwargs) -> models.DecimalField:
    """Market cap, liquidity, volume -- large USD amounts, no sub-cent precision needed."""
    return models.DecimalField(max_digits=24, decimal_places=6, **kwargs)


def price_field(**kwargs) -> models.DecimalField:
    """Per-token unit price in USD -- needs many decimal places for low-cap memecoins."""
    return models.DecimalField(max_digits=36, decimal_places=18, **kwargs)


def percentage_field(**kwargs) -> models.DecimalField:
    """A 0-100 score or percentage."""
    return models.DecimalField(max_digits=6, decimal_places=2, **kwargs)


def probability_field(**kwargs) -> models.DecimalField:
    """A 0-1 probability."""
    return models.DecimalField(max_digits=5, decimal_places=4, **kwargs)


def multiple_field(**kwargs) -> models.DecimalField:
    """A price multiple, e.g. 3.8 for "reached 3.8x"."""
    return models.DecimalField(max_digits=10, decimal_places=4, **kwargs)

"""Holder growth feature extraction (PRD S16). Pure functions -- inputs are
explicit snapshots, never queried here (see services.py). PRD S16's core
point: "This token has 1,000 holders" isn't the signal -- "went from 400 to
1,000 holders rapidly" is. Growth acceleration needs three points (two
growth-rate measurements to compare), not just two.
"""

from dataclasses import dataclass, field
from decimal import Decimal


def _pct_change(current: int | None, previous: int | None) -> Decimal | None:
    if current is None or previous is None or previous == 0:
        return None
    return ((Decimal(current) - Decimal(previous)) / Decimal(previous) * 100).quantize(Decimal("0.01"))


@dataclass
class HolderFeatures:
    holder_growth_count: int | None = None
    holder_growth_pct: Decimal | None = None
    holder_growth_acceleration: Decimal | None = None
    concentration_change_pct: Decimal | None = None
    signals: list[str] = field(default_factory=list)


def extract_holder_features(current, previous=None, earlier=None) -> HolderFeatures:
    features = HolderFeatures()

    if previous is not None:
        features.holder_growth_count = current.holder_count - previous.holder_count
        features.holder_growth_pct = _pct_change(current.holder_count, previous.holder_count)

        if features.holder_growth_pct is not None and features.holder_growth_pct >= Decimal("20"):
            features.signals.append(
                f"Holder count grew {features.holder_growth_pct}% "
                f"({previous.holder_count} -> {current.holder_count})"
            )

        if current.top_holder_pct is not None and previous.top_holder_pct is not None:
            features.concentration_change_pct = (
                current.top_holder_pct - previous.top_holder_pct
            ).quantize(Decimal("0.01"))
            if features.concentration_change_pct <= Decimal("-5"):
                features.signals.append("Top holder concentration is diluting (more holders sharing supply)")

    if previous is not None and earlier is not None:
        earlier_growth_pct = _pct_change(previous.holder_count, earlier.holder_count)
        can_compute_acceleration = (
            earlier_growth_pct is not None
            and features.holder_growth_pct is not None
            and earlier_growth_pct != 0
        )
        if can_compute_acceleration:
            features.holder_growth_acceleration = (
                features.holder_growth_pct / earlier_growth_pct
            ).quantize(Decimal("0.0001"))
            if features.holder_growth_acceleration >= 2:
                features.signals.append(
                    f"Holder growth is accelerating ({features.holder_growth_acceleration}x)"
                )

    return features

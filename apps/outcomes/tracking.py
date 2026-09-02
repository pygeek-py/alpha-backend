"""Outcome-tracking pure logic (PRD S26-28, S51). Every input is an explicit
value/snapshot list, never queried here (see apps/outcomes/services.py).

Anchored to Alert, not Prediction -- see apps/outcomes/models.py's
TokenOutcome docstring for why (Batch 11 runs before Batch 12's Prediction
Engine exists).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

# Fixed tracking offsets (PRD S26), in ascending order -- dict preserves
# insertion order so callers can rely on it without re-sorting.
OFFSET_DELTAS: dict[str, timedelta] = {
    "5m": timedelta(minutes=5),
    "10m": timedelta(minutes=10),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "3h": timedelta(hours=3),
    "6h": timedelta(hours=6),
    "12h": timedelta(hours=12),
    "24h": timedelta(hours=24),
}
FINAL_OFFSET = "24h"

# PRD S27's label thresholds, as price multiples of the initial observation.
REACHED_THRESHOLDS = {
    "reached_1_5x": Decimal("1.5"),
    "reached_2x": Decimal("2"),
    "reached_3x": Decimal("3"),
    "reached_5x": Decimal("5"),
    "reached_10x": Decimal("10"),
}
# Only these get a "time to reach" label (PRD S27) -- 1.5x/10x are boolean-only.
TIME_TO_THRESHOLDS = (Decimal("2"), Decimal("3"), Decimal("5"))


def compute_due_offsets(
    *, reference_timestamp: datetime, now: datetime, already_recorded: set[str]
) -> list[str]:
    """Which fixed offsets have come due and don't have a snapshot yet,
    oldest first. A periodic sweep (not one task per offset per token --
    ARCHITECTURE.md S5) calls this each pass to find the work still owed."""
    return [
        label
        for label, delta in OFFSET_DELTAS.items()
        if label not in already_recorded and now >= reference_timestamp + delta
    ]


@dataclass(frozen=True)
class PricePoint:
    timestamp: datetime
    price: Decimal


@dataclass
class PriceExtremes:
    max_multiple: Decimal | None = None
    max_gain_pct: Decimal | None = None
    max_drawdown_pct: Decimal | None = None


def compute_price_extremes(
    *, initial_price: Decimal | None, price_points: list[PricePoint]
) -> PriceExtremes:
    """Peak multiple and worst drawdown observed across `price_points`,
    relative to `initial_price`. Used both for a single offset's cumulative
    max-so-far (PRD S26's "Maximum drawdown"/"Maximum gain" per period) and
    for the outcome's all-time peak (PRD S51's max_multiple)."""
    if initial_price is None or initial_price <= 0 or not price_points:
        return PriceExtremes()

    multiples = [p.price / initial_price for p in price_points if p.price is not None]
    if not multiples:
        return PriceExtremes()

    max_multiple = max(multiples)
    min_multiple = min(multiples)
    return PriceExtremes(
        max_multiple=max_multiple.quantize(Decimal("0.0001")),
        max_gain_pct=((max_multiple - 1) * 100).quantize(Decimal("0.01")),
        max_drawdown_pct=((min_multiple - 1) * 100).quantize(Decimal("0.01")),
    )


@dataclass
class OutcomeLabels:
    max_multiple: Decimal | None = None
    max_drawdown_pct: Decimal | None = None
    reached_1_5x: bool = False
    reached_2x: bool = False
    reached_3x: bool = False
    reached_5x: bool = False
    reached_10x: bool = False
    time_to_2x: timedelta | None = None
    time_to_3x: timedelta | None = None
    time_to_5x: timedelta | None = None


def compute_outcome_labels(
    *, initial_price: Decimal | None, reference_timestamp: datetime, price_points: list[PricePoint]
) -> OutcomeLabels:
    """The all-time labels for a TokenOutcome (PRD S27), recomputed fresh
    from the full price history each sweep pass -- simple and correct rather
    than maintaining incremental state that could drift.
    """
    extremes = compute_price_extremes(initial_price=initial_price, price_points=price_points)
    if extremes.max_multiple is None:
        return OutcomeLabels()

    labels = OutcomeLabels(max_multiple=extremes.max_multiple, max_drawdown_pct=extremes.max_drawdown_pct)
    for field_name, threshold in REACHED_THRESHOLDS.items():
        setattr(labels, field_name, extremes.max_multiple >= threshold)

    time_to_field = {Decimal("2"): "time_to_2x", Decimal("3"): "time_to_3x", Decimal("5"): "time_to_5x"}
    ordered_points = sorted(
        (p for p in price_points if p.price is not None and initial_price), key=lambda p: p.timestamp
    )
    found: set[Decimal] = set()
    for point in ordered_points:
        multiple = point.price / initial_price
        for threshold in TIME_TO_THRESHOLDS:
            if threshold in found:
                continue
            if multiple >= threshold:
                setattr(labels, time_to_field[threshold], point.timestamp - reference_timestamp)
                found.add(threshold)

    return labels


def is_tracking_complete(*, recorded_offsets: set[str]) -> bool:
    return FINAL_OFFSET in recorded_offsets

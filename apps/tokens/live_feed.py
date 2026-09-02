"""Live Token Feed sort/filter (PRD S40). Pure functions -- operate on an
already-assembled list of row dicts, never query anything themselves (see
apps/tokens/services.py for that). A plain Python sort/filter over an
in-memory list is the right scope at V1 token counts (same reasoning as
apps/core/services.py's per-token loops); a real queryset-level
implementation is the natural upgrade path once token counts grow.
"""

from decimal import Decimal

ORDERABLE_FIELDS = {
    "age_seconds",
    "market_cap",
    "liquidity_usd",
    "volume_5m_usd",
    "holder_count",
    "momentum_score",
    "smart_money_count",
    "risk_score",
    "opportunity_score",
}
DEFAULT_ORDERING = "-opportunity_score"


def sort_rows(rows: list[dict], ordering: str) -> list[dict]:
    """`ordering` is a field name, optionally prefixed with '-' for
    descending (DRF OrderingFilter convention). Rows missing the sort
    field always sort last regardless of direction -- missing data should
    never look like "the worst" or "the best," just absent. Falls back to
    the default ordering for an unrecognized field name rather than
    raising, since this reads query-string input.
    """
    descending = ordering.startswith("-")
    field = ordering[1:] if descending else ordering
    if field not in ORDERABLE_FIELDS:
        field = DEFAULT_ORDERING[1:]
        descending = True

    def sort_key(row: dict) -> tuple:
        value = row.get(field)
        if value is None:
            return (1, Decimal("0"))
        signed = -value if descending else value
        return (0, signed)

    return sorted(rows, key=sort_key)


def filter_rows(rows: list[dict], *, state: str | None = None) -> list[dict]:
    if state is None:
        return rows
    return [row for row in rows if row.get("state") == state]

"""Alert message rendering (PRD S37 "Why Now?" Alert Principle, S38). Pure
functions -- every input is an already-gathered value, never queried here
(see apps/telegram/services.py for that).

The message must never simply say "BUY $TOKEN" (PRD S37) -- every field here
exists to answer "why am I receiving this alert now?" Fields with no data
are shown as "Unknown" rather than fabricated (project-wide honesty rule),
never silently omitted in a way that could read as "zero."
"""

from dataclasses import dataclass, field
from decimal import Decimal

TEST_MESSAGE_PREFIX = "[TEST MESSAGE]"

_STATE_LABELS = {
    "watching": "WATCHING",
    "developing": "DEVELOPING",
    "confirmed": "CONFIRMED",
    "breakout": "BREAKOUT",
    "invalidated": "INVALIDATED",
}


@dataclass
class AlertMessageContext:
    token_symbol: str
    state: str
    market_cap: Decimal | None = None
    liquidity_usd: Decimal | None = None
    probability_2x: Decimal | None = None
    probability_3x: Decimal | None = None
    narrative_name: str = ""
    narrative_strength: Decimal | None = None
    narrative_momentum: Decimal | None = None
    momentum_score: Decimal | None = None
    holder_growth_pct: Decimal | None = None
    smart_money_count: int = 0
    buy_pressure_pct: Decimal | None = None
    risk_score: Decimal | None = None
    reasons: list[str] = field(default_factory=list)
    is_priority: bool = False
    is_test: bool = False


def _usd(value: Decimal | None) -> str:
    if value is None:
        return "Unknown"
    if value >= 1_000_000:
        return f"${(value / 1_000_000).quantize(Decimal('0.1'))}M"
    if value >= 1_000:
        return f"${(value / 1_000).quantize(Decimal('0.1'))}K"
    return f"${value.quantize(Decimal('0.01'))}"


def _pct(value: Decimal | None, *, signed: bool = False) -> str:
    if value is None:
        return "Unknown"
    sign = "+" if signed and value >= 0 else ""
    return f"{sign}{value.quantize(Decimal('0.1'))}%"


def _score(value: Decimal | None, *, out_of: int = 100) -> str:
    if value is None:
        return "Unknown"
    return f"{value.quantize(Decimal('0.1'))}/{out_of}"


def _probability_pct(value: Decimal | None) -> str:
    if value is None:
        return "Unknown"
    return f"{(value * 100).quantize(Decimal('0.1'))}%"


def render_alert_message(context: AlertMessageContext) -> str:
    state_label = _STATE_LABELS.get(context.state, context.state.upper())
    lines = []

    if context.is_test:
        lines.append(TEST_MESSAGE_PREFIX)
    if context.is_priority:
        lines.append("*** PRIORITY OPPORTUNITY ***")

    lines.append(f"${context.token_symbol} -- {state_label}")
    lines.append("")
    lines.append(f"Market Cap: {_usd(context.market_cap)}")
    lines.append(f"Liquidity: {_usd(context.liquidity_usd)}")
    lines.append("")
    lines.append(f"2X Probability: {_probability_pct(context.probability_2x)}")
    lines.append(f"3X Probability: {_probability_pct(context.probability_3x)}")
    lines.append("")

    if context.narrative_name:
        lines.append(f"Narrative: {context.narrative_name}")
        lines.append(f"Narrative Strength: {_score(context.narrative_strength)}")
        lines.append(f"Narrative Momentum: {_score(context.narrative_momentum)}")
        lines.append("")

    lines.append(f"Momentum: {_score(context.momentum_score)}")
    lines.append(f"Holder Growth: {_pct(context.holder_growth_pct, signed=True)}")
    lines.append(f"Smart Money: {context.smart_money_count} tracked wallet(s)")
    lines.append(f"Buy Pressure: {_pct(context.buy_pressure_pct)}")
    lines.append(f"Risk: {_score(context.risk_score)}")
    lines.append("")

    lines.append("WHY NOW?")
    if context.reasons:
        lines.extend(f"- {reason}" for reason in context.reasons)
    else:
        lines.append("- (no specific signal-delta reasons recorded)")
    lines.append("")

    if context.state == "invalidated":
        lines.append("This previously alerted setup has broken down.")
        lines.append("")

    lines.append(f"Status: {state_label}")

    return "\n".join(lines)

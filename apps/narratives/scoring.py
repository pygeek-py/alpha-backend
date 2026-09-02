"""Narrative-level strength/momentum/competition (PRD S19, S22). Pure
functions given pre-aggregated numbers -- apps/narratives/services.py does
the querying.

Honesty note: with no real social provider configured (ARCHITECTURE.md S10:
on-chain-only for V1), "strength" here means observable on-chain narrative
activity -- how many active tokens carry it and how much they're trading,
not social buzz. `blend_with_social_signal` is the seam where a real
SocialDataProvider plugs in later without restructuring anything above it;
until then these functions work correctly on the on-chain proxy alone.
"""

from dataclasses import dataclass
from decimal import Decimal

TOKEN_COUNT_FOR_FULL_STRENGTH = 20
VOLUME_FOR_FULL_STRENGTH = Decimal("100000")
MARKET_CAP_FOR_FULL_STRENGTH = Decimal("5000000")

COMPETITION_LOW_MAX = 5
COMPETITION_MODERATE_MAX = 20


def compute_narrative_strength(
    *, active_token_count: int, total_market_cap: Decimal | None, total_volume_5m: Decimal | None
) -> Decimal:
    """0-100. Three equally-weighted components: how many tokens carry this
    narrative, how much they're trading, and how much they're collectively
    worth -- each capped at a threshold beyond which more doesn't add
    further "strength" (a narrative with 200 tokens isn't 10x stronger than
    one with 20; PRD S22 treats a crowded narrative as a competition
    problem, not a strength bonus).
    """
    token_component = min(Decimal(active_token_count) / TOKEN_COUNT_FOR_FULL_STRENGTH, 1) * Decimal("40")
    volume_component = (
        min((total_volume_5m or Decimal("0")) / VOLUME_FOR_FULL_STRENGTH, 1) * Decimal("30")
    )
    mcap_component = (
        min((total_market_cap or Decimal("0")) / MARKET_CAP_FOR_FULL_STRENGTH, 1) * Decimal("30")
    )
    return (token_component + volume_component + mcap_component).quantize(Decimal("0.01"))


def compute_narrative_momentum(
    current_strength: Decimal, previous_strength: Decimal | None
) -> Decimal | None:
    """0-100, centered at 50 (no change). None if there's no prior
    observation to compare against yet -- never fabricate a "no change"
    reading when the truth is "we don't know."
    """
    if previous_strength is None or previous_strength == 0:
        return None
    pct_change = (current_strength - previous_strength) / previous_strength * 100
    momentum = Decimal("50") + (pct_change / 2)
    return max(Decimal("0"), min(Decimal("100"), momentum)).quantize(Decimal("0.01"))


@dataclass(frozen=True)
class CompetitionLevel:
    active_token_count: int
    label: str  # "low" | "moderate" | "high"


def compute_narrative_competition(active_token_count: int) -> CompetitionLevel:
    if active_token_count <= COMPETITION_LOW_MAX:
        label = "low"
    elif active_token_count <= COMPETITION_MODERATE_MAX:
        label = "moderate"
    else:
        label = "high"
    return CompetitionLevel(active_token_count=active_token_count, label=label)


def blend_with_social_signal(onchain_strength: Decimal, social_signal) -> Decimal:
    """If a real SocialDataProvider is configured and returns a signal,
    blend it 50/50 with the on-chain strength; otherwise return the
    on-chain value unchanged. `social_signal` is a providers.types.NarrativeSignal
    or None.
    """
    if social_signal is None or social_signal.mention_count_previous in (None, 0):
        return onchain_strength

    current = Decimal(social_signal.mention_count_current)
    previous = Decimal(social_signal.mention_count_previous)
    mention_growth_pct = (current - previous) / previous * 100
    social_component = max(Decimal("0"), min(Decimal("100"), Decimal("50") + mention_growth_pct / 2))
    return ((onchain_strength + social_component) / 2).quantize(Decimal("0.01"))

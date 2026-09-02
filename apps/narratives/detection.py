"""Narrative detection (PRD S19, S21). Pure functions -- given a token's
identity text and a list of narratives (each carrying its own `keywords`,
which is DATA on the Narrative row, not a Python constant -- see the model's
docstring for why that's what makes this "a scalable narrative architecture"
rather than a hardcoded list), compute relevance per narrative.

Relevance deliberately isn't a flat "keyword present = 100% relevant" check
-- PRD S21's own example is "AI DOG PEPE 2026 does not automatically qualify
as an AI narrative." A keyword only in the name/symbol scores lower than one
reinforced by the description; multiple distinct keyword matches score
higher than one. This is a deterministic heuristic, not real language
understanding -- it can't tell genuine thematic relevance from a token that
just crammed a trending word into its name, and that limitation is worth
stating plainly rather than overselling what "relevance" means here.
"""

from dataclasses import dataclass
from decimal import Decimal

NAME_MATCH_WEIGHT = Decimal("35")
DESCRIPTION_MATCH_WEIGHT = Decimal("15")
MAX_RELEVANCE = Decimal("100")


@dataclass(frozen=True)
class TokenIdentityText:
    name: str
    symbol: str
    description: str = ""


@dataclass
class NarrativeMatch:
    narrative_id: int
    relevance_score: Decimal
    matched_in_name: list[str]
    matched_in_description: list[str]


def compute_relevance(
    identity: TokenIdentityText, keywords: list[str]
) -> tuple[Decimal, list[str], list[str]]:
    """Returns (relevance_score, keywords matched in name/symbol, keywords
    matched only in the description)."""
    if not keywords:
        return Decimal("0"), [], []

    name_symbol_text = f"{identity.name} {identity.symbol}".lower()
    description_text = (identity.description or "").lower()

    matched_in_name = [kw for kw in keywords if kw.lower() in name_symbol_text]
    matched_in_description = [
        kw for kw in keywords if kw.lower() in description_text and kw not in matched_in_name
    ]

    raw_score = (
        Decimal(len(matched_in_name)) * NAME_MATCH_WEIGHT
        + Decimal(len(matched_in_description)) * DESCRIPTION_MATCH_WEIGHT
    )
    return min(raw_score, MAX_RELEVANCE), matched_in_name, matched_in_description


def detect_narratives_for_token(
    identity: TokenIdentityText, narratives: list, *, min_relevance: Decimal = Decimal("20")
) -> list[NarrativeMatch]:
    """`narratives` is a list of Narrative instances (or anything with `.id`
    and `.keywords`) -- pre-fetched by the caller. Only matches scoring at
    or above `min_relevance` are returned; a single loose keyword hit
    shouldn't be enough to tag a token with a narrative.
    """
    matches = []
    for narrative in narratives:
        score, matched_name, matched_description = compute_relevance(identity, narrative.keywords or [])
        if score >= min_relevance:
            matches.append(
                NarrativeMatch(
                    narrative_id=narrative.id,
                    relevance_score=score,
                    matched_in_name=matched_name,
                    matched_in_description=matched_description,
                )
            )
    return matches

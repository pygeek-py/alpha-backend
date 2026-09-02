"""The deterministic Scoring Engine (PRD S23-24). Pure functions -- every
category scorer takes an already-computed feature object (from Batches 4-7's
safety/market/liquidity/holder/narrative/wallet engines) and returns a
CategoryScore. apps/scoring/services.py gathers those inputs from the
database; nothing in this module queries anything itself.

`score` is None when a category has NO data to work with at all (e.g. no
liquidity snapshot exists yet) -- the aggregator excludes that category
entirely and renormalizes the remaining weights, rather than silently
assuming a neutral value that could hide real risk. That's different from a
category that computed a score from PARTIAL data (some sub-signals known,
some not): that still counts normally, with the gaps disclosed in `missing`.

Weights below are PRD S23's own table for the Opportunity Score. The 2X/3X
weight tables are this project's own initial reweighting of the same nine
category scores (documented per table) -- deliberately provisional, since
there's no historical outcome data yet to calibrate against (that's Batches
11-12's job, and PRD S23 already flags that even the primary weights "must
eventually become configurable and data-driven").
"""

from dataclasses import dataclass, field
from decimal import Decimal

PUMP_AND_DUMP_RISK_PENALTY = Decimal("15")

OPPORTUNITY_WEIGHTS = {
    "safety": Decimal("20"),
    "liquidity": Decimal("15"),
    "momentum": Decimal("15"),
    "holder_growth": Decimal("10"),
    "wallet": Decimal("15"),
    "buy_pressure": Decimal("10"),
    "price_structure": Decimal("5"),
    "narrative": Decimal("5"),
    "creator_history": Decimal("5"),
}

# 2X: emphasizes near-term tradability (momentum, buy pressure, liquidity)
# over long-horizon trust signals (narrative, creator history) -- a quick
# double doesn't need the market to believe a story yet.
SCORE_2X_WEIGHTS = {
    "safety": Decimal("15"),
    "liquidity": Decimal("15"),
    "momentum": Decimal("20"),
    "holder_growth": Decimal("10"),
    "wallet": Decimal("15"),
    "buy_pressure": Decimal("15"),
    "price_structure": Decimal("5"),
    "narrative": Decimal("3"),
    "creator_history": Decimal("2"),
}

# 3X: emphasizes sustained conviction (narrative, wallet intelligence,
# holder growth) and safety over pure momentum -- an initial pump alone
# rarely sustains to a triple; the market needs a reason to keep holding.
SCORE_3X_WEIGHTS = {
    "safety": Decimal("22"),
    "liquidity": Decimal("13"),
    "momentum": Decimal("10"),
    "holder_growth": Decimal("12"),
    "wallet": Decimal("18"),
    "buy_pressure": Decimal("5"),
    "price_structure": Decimal("5"),
    "narrative": Decimal("10"),
    "creator_history": Decimal("5"),
}

assert sum(OPPORTUNITY_WEIGHTS.values()) == 100
assert sum(SCORE_2X_WEIGHTS.values()) == 100
assert sum(SCORE_3X_WEIGHTS.values()) == 100


@dataclass
class CategoryScore:
    score: Decimal | None
    positive: list[str] = field(default_factory=list)
    negative: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def _clamp(value: Decimal) -> Decimal:
    """Bounds to [0, 100] AND quantizes to 2 decimal places -- every
    category scorer routes its final value through here, so this is the one
    place precision hygiene needs to be enforced. Division (narrative
    scoring averages several components) is the operation most likely to
    produce a long, non-terminating Decimal if this weren't centralized;
    percentage_field only has 2 decimal places, so an unquantized value
    would get silently truncated by Postgres on save rather than by us
    deliberately.
    """
    bounded = max(Decimal("0"), min(Decimal("100"), value))
    return bounded.quantize(Decimal("0.01"))


def score_safety(safety_check) -> CategoryScore:
    if safety_check is None:
        return CategoryScore(score=None, missing=["No safety analysis has run for this token yet"])

    positive, negative = [], []
    if safety_check.hard_rejection:
        negative.append(f"Hard safety rejection: {', '.join(safety_check.hard_rejection_reasons)}")
    elif safety_check.score >= 80:
        positive.append(f"Safety score {safety_check.score} ({safety_check.risk_level} risk)")
    else:
        negative.append(f"Safety score only {safety_check.score} ({safety_check.risk_level} risk)")
    for warning in safety_check.warnings:
        negative.append(f"Safety: {warning}")

    return CategoryScore(score=safety_check.score, positive=positive, negative=negative)


def score_liquidity(liquidity_features) -> CategoryScore:
    if liquidity_features is None:
        return CategoryScore(score=None, missing=["No liquidity snapshot available yet"])

    positive, negative, missing = [], [], []
    score = Decimal("50")  # neutral baseline, adjusted by whatever signals are available

    if liquidity_features.liquidity_mcap_ratio_pct is not None:
        ratio = liquidity_features.liquidity_mcap_ratio_pct
        if ratio >= 10:
            score += 25
            positive.append(f"Liquidity is {ratio}% of market cap")
        elif ratio < 3:
            score -= 25
            negative.append(f"Liquidity is only {ratio}% of market cap")
    else:
        missing.append("Liquidity/market-cap ratio unavailable (no market cap data)")

    if liquidity_features.liquidity_change_pct is not None:
        change = liquidity_features.liquidity_change_pct
        if change <= -25:
            score -= 25
            negative.append(f"Liquidity dropped {change}% -- possible pull")
        elif change >= 25:
            score += 10
            positive.append(f"Liquidity grew {change}%")
    else:
        missing.append("No prior liquidity snapshot to compare against")

    return CategoryScore(score=_clamp(score), positive=positive, negative=negative, missing=missing)


def score_momentum(market_features) -> CategoryScore:
    if market_features is None:
        return CategoryScore(score=None, missing=["No market snapshot history available yet"])

    positive, negative, missing = [], [], []
    score = Decimal("50")

    accel = market_features.volume_5m_acceleration
    if accel is not None:
        if accel >= 2:
            score += 25
            positive.append(f"5m volume accelerated {accel}x")
        elif accel < Decimal("0.5"):
            score -= 15
            negative.append(f"5m volume declined to {accel}x of previous")
    else:
        missing.append("No prior snapshot to compute volume acceleration")

    if market_features.price_direction == "up":
        score += 10
        positive.append(f"Price up {market_features.price_change_pct}%")
    elif market_features.price_direction == "down":
        score -= 10
        negative.append(f"Price down {market_features.price_change_pct}%")

    if market_features.pump_and_dump_risk:
        score -= 20
        negative.append("Pump-and-dump pattern detected (price up, sell-dominant volume)")

    return CategoryScore(score=_clamp(score), positive=positive, negative=negative, missing=missing)


def score_holder_growth(holder_features) -> CategoryScore:
    if holder_features is None:
        return CategoryScore(score=None, missing=["No holder snapshot history available yet"])

    positive, negative, missing = [], [], []
    score = Decimal("50")

    if holder_features.holder_growth_pct is not None:
        growth = holder_features.holder_growth_pct
        if growth >= 20:
            score += 20
            positive.append(f"Holder count grew {growth}%")
        elif growth < 0:
            score -= 15
            negative.append(f"Holder count declined {growth}%")
    else:
        missing.append("No prior holder snapshot to compare against")

    if holder_features.holder_growth_acceleration is not None:
        if holder_features.holder_growth_acceleration >= 2:
            score += 15
            positive.append(f"Holder growth accelerating ({holder_features.holder_growth_acceleration}x)")
    else:
        missing.append("Not enough history to assess holder growth acceleration")

    concentration_diluting = (
        holder_features.concentration_change_pct is not None
        and holder_features.concentration_change_pct <= -5
    )
    if concentration_diluting:
        score += 10
        positive.append("Top holder concentration is diluting (healthier distribution)")

    return CategoryScore(score=_clamp(score), positive=positive, negative=negative, missing=missing)


@dataclass
class WalletActivitySummaryForToken:
    smart_money_count: int = 0
    smart_money_avg_reputation: Decimal | None = None
    insider_or_bundled_count: int = 0
    total_tracked_wallets: int = 0


def score_wallet_intelligence(wallet_summary: WalletActivitySummaryForToken | None) -> CategoryScore:
    if wallet_summary is None or wallet_summary.total_tracked_wallets == 0:
        return CategoryScore(score=None, missing=["No wallet transaction data available for this token yet"])

    positive, negative = [], []
    score = Decimal("50")

    if wallet_summary.smart_money_count > 0:
        rep = wallet_summary.smart_money_avg_reputation or Decimal("50")
        score += min(Decimal("40"), Decimal(wallet_summary.smart_money_count) * 10 * (rep / 100))
        positive.append(
            f"{wallet_summary.smart_money_count} tracked smart-money wallet(s) involved "
            f"(avg reputation {rep})"
        )
    else:
        negative.append("No tracked smart-money wallets have entered this token")

    if wallet_summary.insider_or_bundled_count > 0:
        score -= min(Decimal("30"), Decimal(wallet_summary.insider_or_bundled_count) * 15)
        negative.append(
            f"{wallet_summary.insider_or_bundled_count} insider/bundled-wallet pattern(s) detected"
        )

    return CategoryScore(score=_clamp(score), positive=positive, negative=negative)


def score_buy_pressure(market_features) -> CategoryScore:
    if market_features is None or market_features.buy_pressure_pct_5m is None:
        return CategoryScore(score=None, missing=["No recent buy/sell volume split available"])

    positive, negative = [], []
    buy_pct = market_features.buy_pressure_pct_5m
    score = buy_pct  # buy_pressure_pct_5m is already 0-100, directly usable

    if buy_pct >= 65:
        positive.append(f"Buy pressure is {buy_pct}% of volume")
    elif buy_pct <= 35:
        negative.append(f"Sell-dominant volume ({100 - buy_pct}% sell)")

    return CategoryScore(score=_clamp(score), positive=positive, negative=negative)


def score_price_structure(market_features) -> CategoryScore:
    if market_features is None:
        return CategoryScore(score=None, missing=["No market snapshot history available yet"])

    positive, negative, missing = [], [], []
    score = Decimal("50")

    structure = market_features.price_structure
    if structure == "uptrend":
        score += 25
        positive.append("Price structure: higher highs, higher lows (uptrend)")
    elif structure == "downtrend":
        score -= 25
        negative.append("Price structure: lower highs, lower lows (downtrend)")
    elif structure == "consolidating":
        missing.append("Price structure is consolidating -- no clear trend yet")
    else:
        missing.append("Not enough price history to classify structure")

    if market_features.breakout_detected:
        score += 20
        positive.append("Price broke above recent resistance with volume confirmation")

    if market_features.drawdown_from_ath_pct is not None and market_features.drawdown_from_ath_pct >= 50:
        score -= 15
        negative.append(f"{market_features.drawdown_from_ath_pct}% drawdown from recent high")

    return CategoryScore(score=_clamp(score), positive=positive, negative=negative, missing=missing)


def score_narrative(narrative_links: list) -> CategoryScore:
    if not narrative_links:
        return CategoryScore(score=None, missing=["No narrative match detected for this token"])

    best = max(narrative_links, key=lambda link: link.relevance_score or Decimal("0"))
    positive, negative, missing = [], [], []

    components = [best.relevance_score]
    positive.append(f"Matches narrative '{best.narrative.name}' at {best.relevance_score}% relevance")

    if best.strength_score is not None:
        components.append(best.strength_score)
        if best.strength_score >= 60:
            positive.append(f"Narrative strength is {best.strength_score}")
    else:
        missing.append("Narrative strength not yet computed")

    if best.momentum_score is not None:
        components.append(best.momentum_score)
        if best.momentum_score >= 65:
            positive.append(f"Narrative momentum is accelerating ({best.momentum_score})")
        elif best.momentum_score < 35:
            negative.append(f"Narrative momentum is declining ({best.momentum_score})")
    else:
        missing.append("Narrative momentum not yet computed")

    score = sum(components) / len(components)
    return CategoryScore(score=_clamp(score), positive=positive, negative=negative, missing=missing)


def score_creator_history(prior_creator_token_count: int | None) -> CategoryScore:
    if prior_creator_token_count is None:
        return CategoryScore(score=None, missing=["Creator address unknown for this token"])

    if prior_creator_token_count == 0:
        return CategoryScore(
            score=Decimal("70"), positive=["No prior tracked tokens from this creator"]
        )
    if prior_creator_token_count < 3:
        return CategoryScore(
            score=Decimal("55"), positive=[f"Creator has launched {prior_creator_token_count} prior token(s)"]
        )
    if prior_creator_token_count < 8:
        return CategoryScore(
            score=Decimal("30"),
            negative=[f"Creator has launched {prior_creator_token_count} prior tokens"],
        )
    return CategoryScore(
        score=Decimal("10"),
        negative=[
            f"Creator has launched {prior_creator_token_count} prior tokens -- serial deployer pattern"
        ],
    )


def _weighted_aggregate(categories: dict[str, CategoryScore], weights: dict[str, Decimal]) -> Decimal:
    """Renormalizes weights over only the categories that have a score
    (score is not None), so a token missing e.g. wallet data doesn't get
    that category silently treated as neutral."""
    available_weight = sum(weights[name] for name, cat in categories.items() if cat.score is not None)
    if available_weight == 0:
        return Decimal("0")

    total = Decimal("0")
    for name, cat in categories.items():
        if cat.score is not None:
            total += cat.score * (weights[name] / available_weight)
    return _clamp(total)  # _clamp also quantizes -- see its docstring


def compute_risk_score(categories: dict[str, CategoryScore], market_features) -> Decimal:
    safety_score = categories["safety"].score
    base = Decimal("100") - safety_score if safety_score is not None else Decimal("50")
    if market_features is not None and market_features.pump_and_dump_risk:
        base += PUMP_AND_DUMP_RISK_PENALTY
    return _clamp(base)


def build_explanation(categories: dict[str, CategoryScore]) -> dict:
    explanation = {"positive": [], "negative": [], "missing": []}
    for name, cat in categories.items():
        explanation["positive"].extend(f"[{name}] {item}" for item in cat.positive)
        explanation["negative"].extend(f"[{name}] {item}" for item in cat.negative)
        explanation["missing"].extend(f"[{name}] {item}" for item in cat.missing)
    return explanation


@dataclass
class ScoringResult:
    categories: dict[str, CategoryScore]
    opportunity_score: Decimal
    risk_score: Decimal
    score_2x: Decimal
    score_3x: Decimal
    explanation: dict


def compute_token_score(
    *,
    safety_check=None,
    liquidity_features=None,
    market_features=None,
    holder_features=None,
    wallet_summary: WalletActivitySummaryForToken | None = None,
    narrative_links: list | None = None,
    prior_creator_token_count: int | None = None,
) -> ScoringResult:
    categories = {
        "safety": score_safety(safety_check),
        "liquidity": score_liquidity(liquidity_features),
        "momentum": score_momentum(market_features),
        "holder_growth": score_holder_growth(holder_features),
        "wallet": score_wallet_intelligence(wallet_summary),
        "buy_pressure": score_buy_pressure(market_features),
        "price_structure": score_price_structure(market_features),
        "narrative": score_narrative(narrative_links or []),
        "creator_history": score_creator_history(prior_creator_token_count),
    }

    return ScoringResult(
        categories=categories,
        opportunity_score=_weighted_aggregate(categories, OPPORTUNITY_WEIGHTS),
        risk_score=compute_risk_score(categories, market_features),
        score_2x=_weighted_aggregate(categories, SCORE_2X_WEIGHTS),
        score_3x=_weighted_aggregate(categories, SCORE_3X_WEIGHTS),
        explanation=build_explanation(categories),
    )

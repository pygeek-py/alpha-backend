"""Token Safety Engine (PRD S11). Pure analysis logic -- no DB writes here,
so it's testable against plain model instances without touching Postgres.
apps/scoring/services.py is what persists the result as a TokenSafetyCheck.

Every check either passes, warns, or fails outright; a check with no data
available reports itself as "unknown" rather than guessing, per the project's
explainability requirement (PRD S54: the engine must be able to say what
contributed positively, negatively, AND what was missing).

Scoring is a point-deduction model starting from 100 (perfect safety).
Thresholds are module constants for now -- PRD S11 notes these ranges should
eventually be configurable, which is the AI Configuration Engine's job
(Batch 9), not this batch's. Kept as a single dict so that migration is a
drop-in swap later, not a restructuring of the analyzer.
"""

from dataclasses import dataclass, field
from decimal import Decimal

THRESHOLDS = {
    "top_holder_pct_hard_reject": Decimal("70"),
    "top_holder_pct_severe": Decimal("50"),
    "top_holder_pct_warning": Decimal("30"),
    "top5_pct_warning": Decimal("85"),
    "top10_pct_warning": Decimal("92"),
    "min_liquidity_usd_hard_reject": Decimal("500"),
    "min_liquidity_usd_warning": Decimal("5000"),
    "min_liquidity_mcap_ratio_warning": Decimal("0.03"),
    "serial_deployer_warning_count": 3,
    "serial_deployer_severe_count": 8,
    "sell_restriction_min_buy_volume": Decimal("1000"),
    "sell_restriction_min_snapshots": 3,
}

RISK_LEVEL_BANDS = (
    (80, "LOW"),
    (60, "MODERATE"),
    (40, "HIGH"),
    (0, "EXTREME"),
)


def _risk_level_for(score: int) -> str:
    for floor, label in RISK_LEVEL_BANDS:
        if score >= floor:
            return label
    return "EXTREME"


@dataclass
class SafetyAnalysis:
    score: int
    risk_level: str
    checks: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    hard_rejection: bool = False
    hard_rejection_reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "score": self.score,
            "risk_level": self.risk_level,
            "checks": self.checks,
            "warnings": self.warnings,
            "hard_rejection": self.hard_rejection,
            "hard_rejection_reasons": self.hard_rejection_reasons,
        }


class _Accumulator:
    """Collects checks/warnings/deductions/rejections as each check method
    runs, so the analyzer methods stay small and side-effect-free-looking
    while still contributing to one final result."""

    def __init__(self):
        self.checks: list[dict] = []
        self.warnings: list[str] = []
        self.deductions = 0
        self.hard_rejection_reasons: list[str] = []

    def record(self, name: str, passed: bool, detail: str, severity: str = "info", points: int = 0):
        self.checks.append({"name": name, "passed": passed, "detail": detail, "severity": severity})
        if not passed and points:
            self.deductions += points
        if not passed and severity in ("warning", "critical"):
            self.warnings.append(detail)

    def reject(self, reason: str):
        self.hard_rejection_reasons.append(reason)

    def unknown(self, name: str, detail: str):
        self.checks.append({"name": name, "passed": None, "detail": detail, "severity": "unknown"})


def _check_mint_authority(token, acc: _Accumulator) -> None:
    if token.mint_authority_revoked is None:
        acc.unknown("mint_authority", "Mint authority status unknown (not yet checked)")
        return
    if token.mint_authority_revoked:
        acc.record("mint_authority", True, "Mint authority revoked", severity="info")
    else:
        acc.record(
            "mint_authority",
            False,
            "Mint authority is still active -- creator can mint unlimited new supply",
            severity="critical",
            points=40,
        )
        acc.reject("Mint authority not revoked")


def _check_freeze_authority(token, acc: _Accumulator) -> None:
    if token.freeze_authority_revoked is None:
        acc.unknown("freeze_authority", "Freeze authority status unknown (not yet checked)")
        return
    if token.freeze_authority_revoked:
        acc.record("freeze_authority", True, "Freeze authority revoked", severity="info")
    else:
        acc.record(
            "freeze_authority",
            False,
            "Freeze authority is still active -- creator can freeze holder wallets",
            severity="critical",
            points=40,
        )
        acc.reject("Freeze authority not revoked")


def _check_metadata_mutability(token, acc: _Accumulator) -> None:
    if token.is_mutable_metadata is None:
        acc.unknown("metadata_mutability", "Metadata mutability unknown (not yet checked)")
        return
    if token.is_mutable_metadata:
        acc.record(
            "metadata_mutability",
            False,
            "Token metadata is still mutable -- name/image can change after launch",
            severity="warning",
            points=5,
        )
    else:
        acc.record("metadata_mutability", True, "Metadata is immutable", severity="info")


def _check_holder_concentration(holder_snapshot, acc: _Accumulator) -> None:
    if holder_snapshot is None or holder_snapshot.top_holder_pct is None:
        acc.unknown("holder_concentration", "No holder snapshot available yet")
        return

    top1 = holder_snapshot.top_holder_pct
    if top1 > THRESHOLDS["top_holder_pct_hard_reject"]:
        acc.record(
            "holder_concentration",
            False,
            f"Top holder controls {top1}% of supply -- extreme concentration",
            severity="critical",
            points=40,
        )
        acc.reject(f"Top holder holds {top1}% of supply")
    elif top1 > THRESHOLDS["top_holder_pct_severe"]:
        acc.record(
            "holder_concentration",
            False,
            f"Top holder controls {top1}% of supply",
            severity="critical",
            points=25,
        )
    elif top1 > THRESHOLDS["top_holder_pct_warning"]:
        acc.record(
            "holder_concentration",
            False,
            f"Top holder controls {top1}% of supply",
            severity="warning",
            points=10,
        )
    else:
        acc.record("holder_concentration", True, f"Top holder controls {top1}% of supply", severity="info")

    if holder_snapshot.top5_pct is not None and holder_snapshot.top5_pct > THRESHOLDS["top5_pct_warning"]:
        acc.record(
            "top5_concentration",
            False,
            f"Top 5 holders control {holder_snapshot.top5_pct}% of supply",
            severity="warning",
            points=10,
        )
    if holder_snapshot.top10_pct is not None and holder_snapshot.top10_pct > THRESHOLDS["top10_pct_warning"]:
        acc.record(
            "top10_concentration",
            False,
            f"Top 10 holders control {holder_snapshot.top10_pct}% of supply",
            severity="warning",
            points=5,
        )


def _check_liquidity(liquidity_snapshot, market_cap, acc: _Accumulator) -> None:
    if liquidity_snapshot is None:
        # Same three check names used below when a snapshot IS available, so
        # a consumer can always look up "liquidity_amount" etc. by name
        # regardless of whether data existed to evaluate it.
        acc.unknown("liquidity_amount", "No liquidity snapshot available yet")
        acc.unknown("lp_lock_status", "No liquidity snapshot available yet")
        acc.unknown("liquidity_mcap_ratio", "No liquidity snapshot available yet")
        return

    usd = liquidity_snapshot.liquidity_usd
    if usd < THRESHOLDS["min_liquidity_usd_hard_reject"]:
        acc.record(
            "liquidity_amount", False, f"Liquidity is only ${usd} -- trivially rug-pullable",
            severity="critical", points=40,
        )
        acc.reject(f"Liquidity below ${THRESHOLDS['min_liquidity_usd_hard_reject']}")
    elif usd < THRESHOLDS["min_liquidity_usd_warning"]:
        acc.record(
            "liquidity_amount", False, f"Liquidity is low (${usd})", severity="warning", points=15,
        )
    else:
        acc.record("liquidity_amount", True, f"Liquidity is ${usd}", severity="info")

    if liquidity_snapshot.lp_locked is None:
        acc.unknown("lp_lock_status", "LP lock status unknown")
    elif liquidity_snapshot.lp_locked:
        acc.record("lp_lock_status", True, "LP tokens are locked", severity="info")
    else:
        acc.record(
            "lp_lock_status", False, "LP tokens are not locked -- liquidity can be pulled anytime",
            severity="warning", points=15,
        )

    if market_cap and market_cap > 0:
        ratio = usd / market_cap
        if ratio < THRESHOLDS["min_liquidity_mcap_ratio_warning"]:
            acc.record(
                "liquidity_mcap_ratio", False,
                f"Liquidity is only {(ratio * 100).quantize(Decimal('0.1'))}% of market cap",
                severity="warning", points=10,
            )
        else:
            acc.record(
                "liquidity_mcap_ratio", True,
                f"Liquidity is {(ratio * 100).quantize(Decimal('0.1'))}% of market cap", severity="info",
            )
    else:
        acc.unknown("liquidity_mcap_ratio", "No market cap data available yet")


def _check_creator_history(token, prior_creator_token_count: int | None, acc: _Accumulator) -> None:
    if not token.creator_address:
        acc.unknown("creator_history", "Creator address unknown for this token")
        return
    if prior_creator_token_count is None:
        acc.unknown("creator_history", "Creator token history not looked up")
        return

    prior_count = prior_creator_token_count
    if prior_count >= THRESHOLDS["serial_deployer_severe_count"]:
        acc.record(
            "creator_history", False,
            f"Creator has launched {prior_count} other tracked tokens -- serial deployer pattern",
            severity="critical", points=20,
        )
    elif prior_count >= THRESHOLDS["serial_deployer_warning_count"]:
        acc.record(
            "creator_history", False,
            f"Creator has launched {prior_count} other tracked tokens",
            severity="warning", points=10,
        )
    else:
        acc.record(
            "creator_history", True,
            f"Creator has launched {prior_count} other tracked token(s)", severity="info",
        )


def _check_sell_restriction(recent_snapshots, acc: _Accumulator) -> None:
    """Honeypot proxy: sustained buy volume with zero paired sell volume
    across enough snapshots to rule out "just launched, no sells yet"."""
    usable = [
        s for s in recent_snapshots if s.buy_volume_5m is not None and s.sell_volume_5m is not None
    ]
    if len(usable) < THRESHOLDS["sell_restriction_min_snapshots"]:
        acc.unknown("sell_restriction", "Not enough snapshot history to assess sell behavior")
        return

    total_buy = sum((s.buy_volume_5m for s in usable), Decimal("0"))
    total_sell = sum((s.sell_volume_5m for s in usable), Decimal("0"))
    if total_buy >= THRESHOLDS["sell_restriction_min_buy_volume"] and total_sell == 0:
        acc.record(
            "sell_restriction", False,
            f"${total_buy} in buy volume with zero sells across {len(usable)} snapshots -- possible honeypot",
            severity="critical", points=30,
        )
        acc.reject("No sell volume despite sustained buying (possible honeypot)")
    elif total_sell > 0:
        acc.record("sell_restriction", True, "Sell activity observed alongside buy activity", severity="info")
    else:
        acc.record(
            "sell_restriction", True,
            f"Buy volume (${total_buy}) too low to conclusively assess sell behavior",
            severity="info",
        )


def _check_wallet_clustering(acc: _Accumulator) -> None:
    """Not implemented yet -- needs wallet classification/clustering from
    the Wallet Intelligence Engine (Batch 6). Listed explicitly so the
    output is honest about what this analysis does NOT yet cover, rather
    than silently omitting it."""
    acc.unknown(
        "suspicious_wallet_clustering",
        "Requires wallet intelligence (Batch 6) -- not yet analyzed",
    )


def analyze_token_safety(
    token,
    *,
    holder_snapshot=None,
    liquidity_snapshot=None,
    market_cap=None,
    recent_snapshots=(),
    prior_creator_token_count: int | None = None,
) -> SafetyAnalysis:
    """Runs every safety check against a Token plus its most recent
    snapshots and cross-token lookups -- all passed in explicitly rather
    than queried here, so this stays a pure function testable without
    touching the database. apps/scoring/services.py does the querying.
    """
    acc = _Accumulator()

    _check_mint_authority(token, acc)
    _check_freeze_authority(token, acc)
    _check_metadata_mutability(token, acc)
    _check_holder_concentration(holder_snapshot, acc)
    _check_liquidity(liquidity_snapshot, market_cap, acc)
    _check_creator_history(token, prior_creator_token_count, acc)
    _check_sell_restriction(list(recent_snapshots), acc)
    _check_wallet_clustering(acc)

    score = max(0, min(100, 100 - acc.deductions))
    hard_rejection = bool(acc.hard_rejection_reasons)
    risk_level = "EXTREME" if hard_rejection else _risk_level_for(score)

    return SafetyAnalysis(
        score=score,
        risk_level=risk_level,
        checks=acc.checks,
        warnings=acc.warnings,
        hard_rejection=hard_rejection,
        hard_rejection_reasons=acc.hard_rejection_reasons,
    )

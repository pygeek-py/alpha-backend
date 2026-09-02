"""Wallet behavior classification (PRD S18). Pure function given a
pre-computed WalletActivitySummary -- apps/wallets/services.py does the
actual querying/aggregation that builds one.

Checked in priority order, most certain/specific signal first: a wallet
matching an earlier category is never re-labeled by a later, weaker one.
This is what operationalizes PRD S18's core warning -- "a wallet that
repeatedly buys before the creator's tokens pump may not represent
independent smart money" -- INSIDER is checked, and can win, before
SMART_MONEY ever gets a chance to based on the same profitable trades.
"""

from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal

from apps.wallets.models import Wallet

SNIPER_WINDOW_SECONDS = 60
SNIPER_MIN_TOKENS = 3
INSIDER_MIN_SHARED_CREATOR_TOKENS = 2
INSIDER_MIN_SHARE_OF_ENTRIES = Decimal("0.6")  # 60%+ of early entries share one creator
BOT_MIN_TRADES = 30
BOT_MAX_AVG_HOLDING_SECONDS = 60
MARKET_MAKER_MIN_TRADES = 30
MARKET_MAKER_BALANCE_TOLERANCE = Decimal("0.15")  # buy/sell counts within 15% of each other
SMART_MONEY_MIN_EVALUABLE_TRADES = 5
SMART_MONEY_MIN_WIN_RATE = Decimal("55")
SMART_MONEY_MIN_AVG_MULTIPLE = Decimal("1.5")
MIN_TRADES_FOR_NORMAL = 3


@dataclass
class EarlyEntry:
    token_address: str
    creator_address: str
    seconds_after_launch: float


@dataclass
class WalletActivitySummary:
    """Everything classify_wallet() needs, pre-fetched by services.py."""

    trade_count: int = 0
    buy_count: int = 0
    sell_count: int = 0
    is_creator_of_any_token: bool = False
    early_entries: list[EarlyEntry] = field(default_factory=list)
    avg_holding_time_seconds: float | None = None
    is_clustered: bool = False
    evaluable_buy_count: int = 0
    win_rate: Decimal | None = None
    avg_multiple: Decimal | None = None


@dataclass
class ClassificationResult:
    classification: str
    confidence: Decimal
    reasons: list[str] = field(default_factory=list)


def _sniper_entries(summary: WalletActivitySummary) -> list[EarlyEntry]:
    return [e for e in summary.early_entries if e.seconds_after_launch <= SNIPER_WINDOW_SECONDS]


def classify_wallet(summary: WalletActivitySummary) -> ClassificationResult:
    if summary.is_creator_of_any_token:
        return ClassificationResult(
            classification=Wallet.Classification.CREATOR,
            confidence=Decimal("100"),
            reasons=["Wallet has deployed at least one tracked token"],
        )

    sniper_entries = _sniper_entries(summary)
    if len(sniper_entries) >= INSIDER_MIN_SHARED_CREATOR_TOKENS:
        creator_counts = Counter(e.creator_address for e in sniper_entries if e.creator_address)
        if creator_counts:
            top_creator, top_count = creator_counts.most_common(1)[0]
            share = Decimal(top_count) / Decimal(len(sniper_entries))
            if top_count >= INSIDER_MIN_SHARED_CREATOR_TOKENS and share >= INSIDER_MIN_SHARE_OF_ENTRIES:
                return ClassificationResult(
                    classification=Wallet.Classification.INSIDER,
                    confidence=(share * 100).quantize(Decimal("0.01")),
                    reasons=[
                        f"{top_count} of {len(sniper_entries)} early entries are on tokens from the "
                        f"same creator ({top_creator[:8]}...) -- looks tied to that creator, not "
                        "independent skill"
                    ],
                )

    if summary.is_clustered:
        return ClassificationResult(
            classification=Wallet.Classification.BUNDLED,
            confidence=Decimal("70"),
            reasons=["Transaction timing consistently matches other wallets across multiple tokens"],
        )

    if summary.trade_count >= BOT_MIN_TRADES and summary.avg_holding_time_seconds is not None:
        buy_sell_balanced = _is_balanced(summary.buy_count, summary.sell_count)
        if summary.avg_holding_time_seconds <= BOT_MAX_AVG_HOLDING_SECONDS and not (
            summary.trade_count >= MARKET_MAKER_MIN_TRADES and buy_sell_balanced
        ):
            return ClassificationResult(
                classification=Wallet.Classification.BOT,
                confidence=Decimal("75"),
                reasons=[
                    f"{summary.trade_count} trades with a {summary.avg_holding_time_seconds:.0f}s "
                    "average holding time -- mechanical, not manual trading"
                ],
            )

    market_maker_candidate = (
        summary.trade_count >= MARKET_MAKER_MIN_TRADES
        and _is_balanced(summary.buy_count, summary.sell_count)
        and summary.avg_holding_time_seconds is not None
        and summary.avg_holding_time_seconds <= BOT_MAX_AVG_HOLDING_SECONDS
    )
    if market_maker_candidate:
        return ClassificationResult(
            classification=Wallet.Classification.MARKET_MAKER,
            confidence=Decimal("70"),
            reasons=[
                f"{summary.buy_count} buys / {summary.sell_count} sells, tightly balanced and "
                "rapid -- consistent with continuous liquidity provision"
            ],
        )

    if len(sniper_entries) >= SNIPER_MIN_TOKENS:
        return ClassificationResult(
            classification=Wallet.Classification.SNIPER,
            confidence=Decimal("65"),
            reasons=[
                f"Entered {len(sniper_entries)} tokens within {SNIPER_WINDOW_SECONDS}s of launch"
            ],
        )

    if (
        summary.evaluable_buy_count >= SMART_MONEY_MIN_EVALUABLE_TRADES
        and summary.win_rate is not None
        and summary.win_rate >= SMART_MONEY_MIN_WIN_RATE
        and summary.avg_multiple is not None
        and summary.avg_multiple >= SMART_MONEY_MIN_AVG_MULTIPLE
    ):
        return ClassificationResult(
            classification=Wallet.Classification.SMART_MONEY,
            confidence=min(summary.win_rate, Decimal("95")),
            reasons=[
                f"{summary.win_rate}% win rate and {summary.avg_multiple}x average multiple across "
                f"{summary.evaluable_buy_count} evaluated trades, with no insider/bot/cluster pattern "
                "detected"
            ],
        )

    if summary.trade_count >= MIN_TRADES_FOR_NORMAL:
        return ClassificationResult(
            classification=Wallet.Classification.NORMAL,
            confidence=Decimal("50"),
            reasons=["Sufficient trade history but doesn't meet any distinctive pattern's threshold"],
        )

    return ClassificationResult(
        classification=Wallet.Classification.UNKNOWN,
        confidence=Decimal("0"),
        reasons=["Not enough trade history to classify"],
    )


def _is_balanced(buy_count: int, sell_count: int) -> bool:
    total = buy_count + sell_count
    if total == 0:
        return False
    diff_ratio = Decimal(abs(buy_count - sell_count)) / Decimal(total)
    return diff_ratio <= MARKET_MAKER_BALANCE_TOLERANCE

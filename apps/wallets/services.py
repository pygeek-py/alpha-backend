from collections import Counter, defaultdict
from decimal import Decimal

from django.utils import timezone

from apps.market_data.models import TokenSnapshot
from apps.tokens.features import get_token_age
from apps.tokens.models import Token
from apps.wallets import clustering
from apps.wallets.classification import EarlyEntry, WalletActivitySummary, classify_wallet
from apps.wallets.models import Wallet, WalletCluster, WalletPerformance, WalletTransaction
from apps.wallets.performance import (
    BuyEvaluation,
    aggregate_performance,
    compute_reputation_score,
    evaluate_buy,
)
from providers.registry import get_wallet_data_provider

MARKET_CAP_BUCKETS = (
    (Decimal("50000"), "<50k"),
    (Decimal("500000"), "50k-500k"),
    (Decimal("5000000"), "500k-5M"),
    (None, "5M+"),
)


def collect_wallet_transactions(token: Token, *, limit: int = 50) -> list[WalletTransaction]:
    """Fetch recent transactions for `token` and store them, creating any
    not-yet-seen Wallet rows along the way."""
    provider = get_wallet_data_provider()
    items = provider.get_recent_transactions(token.address, limit=limit)

    transactions = []
    for item in items:
        wallet, _ = Wallet.objects.get_or_create(
            address=item.wallet_address,
            defaults={"is_mock": item.is_mock, "source": item.source, "first_seen_at": item.occurred_at},
        )
        transaction, _ = WalletTransaction.objects.get_or_create(
            tx_signature=item.tx_signature,
            defaults={
                "wallet": wallet,
                "token": token,
                "side": item.side,
                "amount_tokens": item.amount_tokens,
                "amount_usd": item.amount_usd,
                "price": item.price,
                "occurred_at": item.occurred_at,
                "is_mock": item.is_mock,
                "source": item.source,
            },
        )
        transactions.append(transaction)

    return transactions


def _market_cap_bucket(market_cap: Decimal) -> str:
    for ceiling, label in MARKET_CAP_BUCKETS:
        if ceiling is None or market_cap < ceiling:
            return label
    return "5M+"


def _market_cap_at(token: Token, at_time) -> Decimal | None:
    """Nearest known market cap at or before `at_time`, falling back to the
    nearest one just after if nothing earlier exists yet."""
    snapshot = (
        TokenSnapshot.objects.filter(token=token, timestamp__lte=at_time).order_by("-timestamp").first()
    )
    if snapshot is None:
        snapshot = (
            TokenSnapshot.objects.filter(token=token, timestamp__gt=at_time).order_by("timestamp").first()
        )
    return snapshot.market_cap if snapshot else None


def _evaluate_wallet_buys(wallet: Wallet) -> list[BuyEvaluation]:
    """For each of the wallet's BUY transactions, evaluate the best price
    the token reached afterward (see performance.py's honesty note on what
    this does and doesn't tell us), matching the earliest subsequent SELL
    on the same token for a holding-time estimate, if any."""
    evaluations = []
    buys = (
        wallet.transactions.filter(side=WalletTransaction.Side.BUY)
        .select_related("token")
        .order_by("occurred_at")
    )
    for buy in buys:
        if not buy.price:
            continue
        subsequent_prices = list(
            TokenSnapshot.objects.filter(token=buy.token, timestamp__gt=buy.occurred_at).values_list(
                "price", flat=True
            )
        )
        matched_sell = (
            wallet.transactions.filter(
                token=buy.token, side=WalletTransaction.Side.SELL, occurred_at__gt=buy.occurred_at
            )
            .order_by("occurred_at")
            .first()
        )
        holding_time = (matched_sell.occurred_at - buy.occurred_at) if matched_sell else None
        evaluation = evaluate_buy(buy.price, subsequent_prices, matched_sell_holding_time=holding_time)
        if evaluation:
            evaluations.append(evaluation)
    return evaluations


def _compute_preferred_buckets(wallet: Wallet) -> tuple[str, str]:
    age_buckets = []
    mcap_buckets = []
    buys = wallet.transactions.filter(side=WalletTransaction.Side.BUY).select_related("token")
    for buy in buys:
        age = get_token_age(buy.token, as_of=buy.occurred_at)
        if age:
            age_buckets.append(age.bucket)
        market_cap = _market_cap_at(buy.token, buy.occurred_at)
        if market_cap is not None:
            mcap_buckets.append(_market_cap_bucket(market_cap))

    preferred_age = Counter(age_buckets).most_common(1)[0][0] if age_buckets else ""
    preferred_mcap = Counter(mcap_buckets).most_common(1)[0][0] if mcap_buckets else ""
    return preferred_age, preferred_mcap


def calculate_wallet_performance(
    wallet: Wallet, *, evaluations: list[BuyEvaluation] | None = None
) -> WalletPerformance:
    """Recomputes and persists the wallet's performance rollup. Pass
    `evaluations` if the caller already computed them (classify_and_score_wallet
    does, to avoid evaluating every buy twice)."""
    if evaluations is None:
        evaluations = _evaluate_wallet_buys(wallet)

    trade_count = wallet.transactions.count()
    metrics = aggregate_performance(evaluations, trade_count=trade_count)
    reputation_score = compute_reputation_score(metrics)
    preferred_age, preferred_mcap = _compute_preferred_buckets(wallet)

    performance, _ = WalletPerformance.objects.update_or_create(
        wallet=wallet,
        defaults={
            "win_rate": metrics.win_rate,
            "avg_multiple": metrics.avg_multiple,
            "median_multiple": metrics.median_multiple,
            "max_multiple": metrics.max_multiple,
            "avg_holding_time": metrics.avg_holding_time,
            "trade_count": metrics.trade_count,
            "successful_2x_count": metrics.successful_2x_count,
            "successful_3x_count": metrics.successful_3x_count,
            "successful_5x_count": metrics.successful_5x_count,
            "preferred_token_age": preferred_age,
            "preferred_market_cap_range": preferred_mcap,
            "reputation_score": reputation_score,
            "last_calculated_at": timezone.now(),
        },
    )
    return performance


def _build_activity_summary(
    wallet: Wallet, *, evaluations: list[BuyEvaluation], metrics
) -> WalletActivitySummary:
    trade_count = wallet.transactions.count()
    buy_count = wallet.transactions.filter(side=WalletTransaction.Side.BUY).count()
    sell_count = trade_count - buy_count

    is_creator = Token.objects.filter(creator_address=wallet.address).exclude(creator_address="").exists()

    early_entries = []
    buys = wallet.transactions.filter(side=WalletTransaction.Side.BUY).select_related("token")
    for buy in buys:
        token = buy.token
        if token.launched_at is None:
            continue
        seconds_after = (buy.occurred_at - token.launched_at).total_seconds()
        if seconds_after < 0:
            continue
        early_entries.append(
            EarlyEntry(
                token_address=token.address,
                creator_address=token.creator_address,
                seconds_after_launch=seconds_after,
            )
        )

    avg_holding_seconds = metrics.avg_holding_time.total_seconds() if metrics.avg_holding_time else None

    return WalletActivitySummary(
        trade_count=trade_count,
        buy_count=buy_count,
        sell_count=sell_count,
        is_creator_of_any_token=is_creator,
        early_entries=early_entries,
        avg_holding_time_seconds=avg_holding_seconds,
        is_clustered=wallet.cluster_id is not None,
        evaluable_buy_count=metrics.evaluable_buy_count,
        win_rate=metrics.win_rate,
        avg_multiple=metrics.avg_multiple,
    )


def classify_and_score_wallet(wallet: Wallet) -> tuple[Wallet, WalletPerformance]:
    """Orchestrates a full re-evaluation of one wallet: performance rollup,
    then classification built from that same performance data plus
    behavioral signals (creator check, early-entry timing, cluster
    membership). Clustering itself is NOT recomputed here -- it's a global,
    cross-wallet pass (see run_wallet_clustering); this just reads whatever
    cluster the wallet was last assigned to. Returns (wallet, performance).
    """
    evaluations = _evaluate_wallet_buys(wallet)
    performance = calculate_wallet_performance(wallet, evaluations=evaluations)
    trade_count = wallet.transactions.count()
    metrics = aggregate_performance(evaluations, trade_count=trade_count)

    summary = _build_activity_summary(wallet, evaluations=evaluations, metrics=metrics)
    result = classify_wallet(summary)

    wallet.classification = result.classification
    wallet.classification_confidence = result.confidence
    wallet.classification_reasons = result.reasons
    wallet.save(update_fields=["classification", "classification_confidence", "classification_reasons"])

    return wallet, performance


def run_wallet_clustering() -> list[WalletCluster]:
    """Global clustering pass across all current wallet-transaction data.
    Creates/updates WalletCluster rows and assigns Wallet.cluster for every
    wallet found in a qualifying group. Existing cluster assignments for
    wallets that no longer qualify are left as-is -- this pass only adds
    evidence, it doesn't retract prior findings (a wallet doesn't stop
    having been observed clustering just because the current dataset window
    doesn't reconfirm it every run).
    """
    transactions_by_token = defaultdict(list)
    for tx in WalletTransaction.objects.select_related("wallet", "token").iterator():
        transactions_by_token[tx.token.address].append(
            clustering.TxRecord(wallet_address=tx.wallet.address, occurred_at=tx.occurred_at, side=tx.side)
        )

    found_clusters = clustering.find_wallet_clusters(transactions_by_token)

    cluster_rows = []
    for found in found_clusters:
        confidence = min(Decimal(found.shared_token_count) * 20, Decimal("95"))
        cluster_row = WalletCluster.objects.create(
            shared_token_count=found.shared_token_count,
            confidence=confidence,
            detected_at=timezone.now(),
        )
        Wallet.objects.filter(address__in=found.wallet_addresses).update(cluster=cluster_row)
        cluster_rows.append(cluster_row)

    return cluster_rows

import logging
from datetime import timedelta

from django.utils import timezone

from apps.tokens.live_feed import DEFAULT_ORDERING, filter_rows, sort_rows
from apps.tokens.models import Token
from providers.registry import get_chain_provider

logger = logging.getLogger("alpha.ingestion")


def discover_tokens(*, limit: int = 50) -> list[Token]:
    """Discover new/trending tokens via the configured chain provider and
    upsert them into the registry. Existing tokens are updated in place
    (address is the natural key) rather than duplicated."""
    provider = get_chain_provider()
    discovered = provider.discover_tokens(limit=limit)

    tokens = []
    for item in discovered:
        token, created = Token.objects.update_or_create(
            address=item.address,
            defaults={
                "symbol": item.symbol,
                "name": item.name,
                "decimals": item.decimals,
                "creator_address": item.creator_address,
                "launched_at": item.launched_at,
                "mint_authority_revoked": item.mint_authority_revoked,
                "freeze_authority_revoked": item.freeze_authority_revoked,
                "is_mutable_metadata": item.is_mutable_metadata,
                "top_holder_pct_at_launch": item.top_holder_pct_at_launch,
                "is_mock": item.is_mock,
                "source": item.source,
            },
        )
        tokens.append(token)
        if created:
            logger.info("Discovered new token %s (%s)", token.symbol, token.address)

    return tokens


def get_active_token_ids() -> list[int]:
    """Tokens the ingestion sweep tasks (market_data/liquidity/holders) should
    poll. A single shared query so every collector's fan-out task agrees on
    what "active" means, rather than each app re-deriving its own filter."""
    return list(Token.objects.filter(is_active=True).values_list("id", flat=True))


def _smart_money_count(token_id: int) -> int:
    from apps.wallets.models import Wallet, WalletTransaction

    return (
        WalletTransaction.objects.filter(
            token_id=token_id, wallet__classification=Wallet.Classification.SMART_MONEY
        )
        .values("wallet_id")
        .distinct()
        .count()
    )


def _build_live_feed_row(token: Token, *, now) -> dict:
    from apps.alerts.models import AlertEvent
    from apps.holders.models import HolderSnapshot
    from apps.liquidity.models import LiquiditySnapshot
    from apps.market_data.models import TokenSnapshot

    score = token.scores.order_by("-timestamp").first()
    snapshot = TokenSnapshot.objects.filter(token=token).order_by("-timestamp").first()
    liquidity = LiquiditySnapshot.objects.filter(token=token).order_by("-timestamp").first()
    holders = HolderSnapshot.objects.filter(token=token).order_by("-timestamp").first()
    top_narrative_link = (
        token.narrative_links.select_related("narrative").order_by("-relevance_score").first()
    )
    latest_event = AlertEvent.objects.filter(token=token).order_by("-triggered_at").first()

    reference_time = token.launched_at or token.created_at
    age_seconds = int((now - reference_time).total_seconds())

    return {
        "token_id": token.id,
        "address": token.address,
        "symbol": token.symbol or token.address[:8],
        "age_seconds": age_seconds,
        "market_cap": snapshot.market_cap if snapshot else None,
        "liquidity_usd": liquidity.liquidity_usd if liquidity else None,
        "volume_5m_usd": snapshot.volume_5m if snapshot else None,
        "holder_count": holders.holder_count if holders else None,
        "momentum_score": score.momentum_score if score else None,
        "narrative_name": top_narrative_link.narrative.name if top_narrative_link else None,
        "smart_money_count": _smart_money_count(token.id),
        "risk_score": score.risk_score if score else None,
        "opportunity_score": score.opportunity_score if score else None,
        "state": latest_event.to_state if latest_event else "discovered",
    }


LIVE_FEED_ROW_LIMIT = 200


def get_live_feed(*, ordering: str = DEFAULT_ORDERING, state: str | None = None) -> list[dict]:
    """PRD S40: currently monitored tokens with the columns the Live Feed
    page needs, sortable/filterable. Point-in-time correctness isn't a
    concern here (unlike outcome tracking) -- this reads whatever the
    LATEST snapshot/score of each active token currently is.

    Capped at LIVE_FEED_ROW_LIMIT (matching apps/alerts's same-sized cap) --
    real token/candidate counts are small today, but this endpoint has no
    other bound. `_build_live_feed_row` also does ~6 queries per token
    (snapshot/liquidity/holder/score/narrative/wallet lookups), which is a
    known N+1 pattern worth batching if active token counts grow into the
    hundreds -- not fixed here since it's real work for zero benefit at
    today's real data volume (documented, not silently left broken).
    """
    now = timezone.now()
    token_ids = get_active_token_ids()
    rows = [_build_live_feed_row(Token.objects.get(pk=token_id), now=now) for token_id in token_ids]
    rows = filter_rows(rows, state=state)
    return sort_rows(rows, ordering)[:LIVE_FEED_ROW_LIMIT]


_CATEGORY_SCORE_FIELDS = (
    "safety_score",
    "liquidity_score",
    "momentum_score",
    "holder_growth_score",
    "wallet_score",
    "buy_pressure_score",
    "price_structure_score",
    "narrative_score",
    "creator_score",
)


def _score_breakdown(score, *, now) -> dict | None:
    if score is None:
        return None
    return {
        "opportunity_score": score.opportunity_score,
        "risk_score": score.risk_score,
        "score_2x": score.score_2x,
        "score_3x": score.score_3x,
        "categories": {field: getattr(score, field) for field in _CATEGORY_SCORE_FIELDS},
        "explanation": score.explanation,
        "computed_at": score.timestamp,
        "age_seconds": int((now - score.timestamp).total_seconds()),
    }


def _narrative_breakdown(token: Token) -> list[dict]:
    links = token.narrative_links.select_related("narrative").order_by("-relevance_score")
    return [
        {
            "name": link.narrative.name,
            "category": link.narrative.category,
            "relevance_score": link.relevance_score,
            "strength_score": link.strength_score,
            "momentum_score": link.momentum_score,
        }
        for link in links
    ]


def _outcome_breakdown(token: Token) -> dict | None:
    from apps.alerts.models import Alert

    latest_alert = (
        Alert.objects.filter(token=token, outcome__isnull=False).order_by("-created_at").first()
    )
    if latest_alert is None:
        return None
    outcome = latest_alert.outcome
    return {
        "reached_1_5x": outcome.reached_1_5x,
        "reached_2x": outcome.reached_2x,
        "reached_3x": outcome.reached_3x,
        "reached_5x": outcome.reached_5x,
        "reached_10x": outcome.reached_10x,
        "max_multiple": outcome.max_multiple,
        "max_drawdown_pct": outcome.max_drawdown_pct,
        "time_to_2x": outcome.time_to_2x,
        "time_to_3x": outcome.time_to_3x,
        "time_to_5x": outcome.time_to_5x,
        "tracking_complete": outcome.tracking_complete,
    }


def _wallet_activity(token: Token, *, limit: int = 20) -> list[dict]:
    from apps.wallets.models import WalletTransaction

    transactions = (
        WalletTransaction.objects.filter(token=token)
        .select_related("wallet", "wallet__performance")
        .order_by("-occurred_at")[:limit]
    )
    rows = []
    for tx in transactions:
        performance = getattr(tx.wallet, "performance", None)
        rows.append(
            {
                "wallet_address": tx.wallet.address,
                "wallet_label": tx.wallet.label,
                "classification": tx.wallet.classification,
                "reputation_score": performance.reputation_score if performance else None,
                "side": tx.side,
                "amount_usd": tx.amount_usd,
                "occurred_at": tx.occurred_at,
            }
        )
    return rows


def get_token_detail(token_id: int) -> dict:
    """PRD S41 Token Detail Page: everything the page needs in one payload
    except the chart time-series (see get_token_history for that -- a
    different shape of data, kept as a separate fetch)."""
    from apps.alerts.models import AlertEvent
    from apps.holders.models import HolderSnapshot
    from apps.liquidity.models import LiquiditySnapshot
    from apps.market_data.models import TokenSnapshot

    token = Token.objects.get(pk=token_id)
    now = timezone.now()

    score = token.scores.order_by("-timestamp").first()
    snapshot = TokenSnapshot.objects.filter(token=token).order_by("-timestamp").first()
    liquidity = LiquiditySnapshot.objects.filter(token=token).order_by("-timestamp").first()
    holders = HolderSnapshot.objects.filter(token=token).order_by("-timestamp").first()
    latest_event = AlertEvent.objects.filter(token=token).order_by("-triggered_at").first()

    reference_time = token.launched_at or token.created_at
    age_seconds = int((now - reference_time).total_seconds())

    return {
        "overview": {
            "token_id": token.id,
            "address": token.address,
            "symbol": token.symbol or token.address[:8],
            "name": token.name,
            "age_seconds": age_seconds,
            "market_cap": snapshot.market_cap if snapshot else None,
            "liquidity_usd": liquidity.liquidity_usd if liquidity else None,
            "volume_5m_usd": snapshot.volume_5m if snapshot else None,
            "holder_count": holders.holder_count if holders else None,
            "state": latest_event.to_state if latest_event else "discovered",
        },
        "score": _score_breakdown(score, now=now),
        "narratives": _narrative_breakdown(token),
        "outcome": _outcome_breakdown(token),
        "wallet_activity": _wallet_activity(token),
    }


def get_token_history(token_id: int, *, hours: int = 24) -> dict:
    """PRD S41's price/volume/holder-growth charts. A separate fetch from
    get_token_detail since this can be many rows -- a different data shape
    for a different UI need (charts vs a summary panel)."""
    from apps.holders.models import HolderSnapshot
    from apps.market_data.models import TokenSnapshot

    since = timezone.now() - timedelta(hours=hours)
    price_points = TokenSnapshot.objects.filter(token_id=token_id, timestamp__gte=since).order_by(
        "timestamp"
    )
    holder_points = HolderSnapshot.objects.filter(token_id=token_id, timestamp__gte=since).order_by(
        "timestamp"
    )

    return {
        "price": [
            {"timestamp": s.timestamp, "price": s.price, "volume_5m": s.volume_5m}
            for s in price_points
        ],
        "holders": [{"timestamp": h.timestamp, "holder_count": h.holder_count} for h in holder_points],
    }

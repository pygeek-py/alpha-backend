from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.alerts.models import Alert, AlertState
from apps.holders.services import get_holder_features
from apps.liquidity.models import LiquiditySnapshot
from apps.market_data.models import TokenSnapshot
from apps.market_data.services import get_market_features
from apps.telegram.client import TelegramClient, TelegramError
from apps.telegram.models import TelegramConnection
from apps.telegram.templates import AlertMessageContext, render_alert_message
from apps.wallets.models import Wallet, WalletTransaction

# WATCHING is intentionally absent -- PRD S36: "Default: Dashboard only",
# never a Telegram send regardless of connection settings.
STATE_TOGGLE_FIELD = {
    AlertState.DEVELOPING: "notify_developing",
    AlertState.CONFIRMED: "notify_confirmed",
    AlertState.BREAKOUT: "notify_breakout",
    AlertState.INVALIDATED: "notify_invalidated",
}

# How far back the periodic delivery sweep looks for undelivered alerts.
# Bounds the query and avoids retroactively flooding Telegram with stale
# alerts if notifications are enabled long after they fired.
DELIVERY_WINDOW = timedelta(hours=2)


def get_active_connection() -> TelegramConnection | None:
    return TelegramConnection.objects.filter(is_active=True).first()


def is_alert_eligible_for_delivery(alert: Alert, connection: TelegramConnection) -> bool:
    if alert.is_priority and connection.notify_priority:
        return True
    toggle_field = STATE_TOGGLE_FIELD.get(alert.state)
    if toggle_field is None:
        return False
    return getattr(connection, toggle_field)


def _smart_money_count(token_id: int) -> int:
    return (
        WalletTransaction.objects.filter(
            token_id=token_id, wallet__classification=Wallet.Classification.SMART_MONEY
        )
        .values("wallet_id")
        .distinct()
        .count()
    )


def build_alert_message_context(alert: Alert) -> AlertMessageContext:
    token = alert.token
    latest_snapshot = TokenSnapshot.objects.filter(token=token).order_by("-timestamp").first()
    latest_liquidity = LiquiditySnapshot.objects.filter(token=token).order_by("-timestamp").first()
    top_narrative_link = (
        token.narrative_links.select_related("narrative").order_by("-relevance_score").first()
    )
    latest_score = token.scores.order_by("-timestamp").first()
    market_features = get_market_features(token)
    holder_features = get_holder_features(token)

    return AlertMessageContext(
        token_symbol=token.symbol or token.address[:8],
        state=alert.state,
        market_cap=latest_snapshot.market_cap if latest_snapshot else None,
        liquidity_usd=latest_liquidity.liquidity_usd if latest_liquidity else None,
        probability_2x=alert.probability_2x,
        probability_3x=alert.probability_3x,
        narrative_name=top_narrative_link.narrative.name if top_narrative_link else "",
        narrative_strength=top_narrative_link.strength_score if top_narrative_link else None,
        narrative_momentum=top_narrative_link.momentum_score if top_narrative_link else None,
        momentum_score=latest_score.momentum_score if latest_score else None,
        holder_growth_pct=holder_features.holder_growth_pct if holder_features else None,
        smart_money_count=_smart_money_count(token.id),
        buy_pressure_pct=market_features.buy_pressure_pct_5m if market_features else None,
        risk_score=alert.risk_score,
        reasons=alert.reasons,
        is_priority=alert.is_priority,
    )


def send_alert_notification(alert: Alert) -> bool:
    """Sends `alert` to the operator's Telegram if a connection exists and
    is configured to receive this alert type. Returns False (not an error)
    when there's simply nothing to deliver to, or the alert type is
    disabled; raises TelegramError if delivery was attempted and failed."""
    connection = get_active_connection()
    if connection is None:
        return False
    if not is_alert_eligible_for_delivery(alert, connection):
        return False

    context = build_alert_message_context(alert)
    message = render_alert_message(context)

    TelegramClient().send_message(chat_id=connection.chat_id, text=message)

    Alert.objects.filter(pk=alert.pk).update(telegram_sent=True, telegram_sent_at=timezone.now())
    return True


def pending_alert_ids(*, window: timedelta = DELIVERY_WINDOW) -> list[int]:
    cutoff = timezone.now() - window
    return list(
        Alert.objects.filter(telegram_sent=False, created_at__gte=cutoff)
        .exclude(state=AlertState.WATCHING)
        .values_list("id", flat=True)
    )


def _test_message_context() -> AlertMessageContext:
    """A synthetic context using PRD S37's own worked example values, so
    what the user sees in setup is representative of a real alert -- clearly
    labeled as a test (PRD S38 point 6 / ARCHITECTURE.md S9)."""
    return AlertMessageContext(
        token_symbol="TESTCOIN",
        state=AlertState.CONFIRMED,
        market_cap=Decimal("240000"),
        liquidity_usd=Decimal("78000"),
        probability_2x=Decimal("0.87"),
        probability_3x=Decimal("0.71"),
        narrative_name="Example Narrative",
        narrative_strength=Decimal("91"),
        narrative_momentum=Decimal("94"),
        momentum_score=Decimal("89"),
        holder_growth_pct=Decimal("42"),
        smart_money_count=6,
        buy_pressure_pct=Decimal("72"),
        risk_score=Decimal("17"),
        reasons=[
            "This is a test message to confirm your Telegram connection works.",
            "Real alerts will look like this, with real numbers.",
        ],
        is_test=True,
    )


def send_test_alert(connection: TelegramConnection) -> None:
    """PRD S38 point 6: sends a synthetic test alert through the SAME
    rendering path real alerts use. Raises TelegramError on failure --
    callers (the /telegram/test/ endpoint) surface that to the user."""
    message = render_alert_message(_test_message_context())
    try:
        TelegramClient().send_message(chat_id=connection.chat_id, text=message)
    except TelegramError:
        TelegramConnection.objects.filter(pk=connection.pk).update(
            last_test_at=timezone.now(), last_test_success=False
        )
        raise
    TelegramConnection.objects.filter(pk=connection.pk).update(
        last_test_at=timezone.now(), last_test_success=True
    )

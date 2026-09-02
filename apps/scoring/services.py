from decimal import Decimal

from django.utils import timezone

from apps.holders.services import get_holder_features
from apps.liquidity.services import get_liquidity_features
from apps.market_data.services import get_market_features
from apps.narratives.services import detect_token_narratives
from apps.scoring.engine import WalletActivitySummaryForToken, compute_token_score
from apps.scoring.models import TokenSafetyCheck, TokenScore
from apps.scoring.safety import analyze_token_safety
from apps.tokens.models import Token
from apps.wallets.models import Wallet, WalletPerformance


def _prior_creator_token_count(token: Token) -> int | None:
    if not token.creator_address:
        return None
    return Token.objects.filter(creator_address=token.creator_address).exclude(pk=token.pk).count()


def run_safety_analysis(token: Token) -> TokenSafetyCheck:
    """Gathers the latest available snapshots for `token`, runs the safety
    engine, and persists the result. This is the one place that queries the
    database for safety analysis -- apps/scoring/safety.py itself stays a
    pure function so it's testable without touching Postgres.
    """
    holder_snapshot = token.holder_snapshots.order_by("-timestamp").first()
    liquidity_snapshot = token.liquidity_snapshots.order_by("-timestamp").first()
    latest_token_snapshot = token.snapshots.order_by("-timestamp").first()
    market_cap = latest_token_snapshot.market_cap if latest_token_snapshot else None
    recent_snapshots = list(token.snapshots.order_by("-timestamp")[:5])
    prior_creator_token_count = _prior_creator_token_count(token)

    analysis = analyze_token_safety(
        token,
        holder_snapshot=holder_snapshot,
        liquidity_snapshot=liquidity_snapshot,
        market_cap=market_cap,
        recent_snapshots=recent_snapshots,
        prior_creator_token_count=prior_creator_token_count,
    )

    return TokenSafetyCheck.objects.create(
        token=token,
        timestamp=timezone.now(),
        score=analysis.score,
        risk_level=analysis.risk_level,
        hard_rejection=analysis.hard_rejection,
        hard_rejection_reasons=analysis.hard_rejection_reasons,
        checks=analysis.checks,
        warnings=analysis.warnings,
    )


def _build_wallet_activity_summary(token: Token) -> WalletActivitySummaryForToken:
    wallets = Wallet.objects.filter(transactions__token=token).distinct()
    total = wallets.count()
    if total == 0:
        return WalletActivitySummaryForToken(total_tracked_wallets=0)

    smart_money = wallets.filter(classification=Wallet.Classification.SMART_MONEY)
    smart_money_count = smart_money.count()

    avg_reputation = None
    if smart_money_count:
        reputations = list(
            WalletPerformance.objects.filter(
                wallet__in=smart_money, reputation_score__isnull=False
            ).values_list("reputation_score", flat=True)
        )
        if reputations:
            avg_reputation = (sum(reputations) / len(reputations)).quantize(Decimal("0.01"))

    insider_or_bundled_count = wallets.filter(
        classification__in=[Wallet.Classification.INSIDER, Wallet.Classification.BUNDLED]
    ).count()

    return WalletActivitySummaryForToken(
        smart_money_count=smart_money_count,
        smart_money_avg_reputation=avg_reputation,
        insider_or_bundled_count=insider_or_bundled_count,
        total_tracked_wallets=total,
    )


def compute_and_persist_token_score(token: Token) -> TokenScore:
    """Runs the full Scoring Engine for `token` and persists the result.

    Safety and narrative detection are recomputed fresh here rather than
    reading whatever the last periodic run left behind -- both are cheap,
    purely-local computations (no external API calls), so there's no reason
    to risk scoring against a stale safety/narrative read when getting a
    fresh one costs nothing. Liquidity/market/holder features and wallet
    activity, by contrast, are read from whatever snapshots/transactions
    already exist -- those come from separately-scheduled ingestion tasks
    that call external providers, which this function must never trigger.
    """
    safety_check = run_safety_analysis(token)
    # detect_token_narratives() is called for its side effect (keeping
    # matches current) -- its return value is only THIS call's matches, not
    # the token's full current narrative state. A link from an earlier run
    # that this pass doesn't re-confirm (e.g. keywords changed) still
    # genuinely exists and must still count toward scoring, so read it back
    # from the database rather than trusting the return value.
    detect_token_narratives(token)
    narrative_links = list(token.narrative_links.select_related("narrative").all())
    liquidity_features = get_liquidity_features(token)
    market_features = get_market_features(token)
    holder_features = get_holder_features(token)
    wallet_summary = _build_wallet_activity_summary(token)
    prior_creator_token_count = _prior_creator_token_count(token)

    result = compute_token_score(
        safety_check=safety_check,
        liquidity_features=liquidity_features,
        market_features=market_features,
        holder_features=holder_features,
        wallet_summary=wallet_summary,
        narrative_links=narrative_links,
        prior_creator_token_count=prior_creator_token_count,
    )
    categories = result.categories

    return TokenScore.objects.create(
        token=token,
        timestamp=timezone.now(),
        safety_score=categories["safety"].score,
        liquidity_score=categories["liquidity"].score,
        momentum_score=categories["momentum"].score,
        holder_growth_score=categories["holder_growth"].score,
        wallet_score=categories["wallet"].score,
        buy_pressure_score=categories["buy_pressure"].score,
        price_structure_score=categories["price_structure"].score,
        narrative_score=categories["narrative"].score,
        creator_score=categories["creator_history"].score,
        opportunity_score=result.opportunity_score,
        risk_score=result.risk_score,
        score_2x=result.score_2x,
        score_3x=result.score_3x,
        explanation=result.explanation,
    )

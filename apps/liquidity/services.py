from apps.liquidity.features import LiquidityFeatures, extract_liquidity_features
from apps.liquidity.models import LiquiditySnapshot
from apps.tokens.models import Token
from providers.registry import get_market_data_provider


def collect_liquidity(token: Token) -> LiquiditySnapshot:
    """Fetch a current liquidity snapshot for `token` and store it."""
    provider = get_market_data_provider()
    data = provider.get_liquidity_snapshot(token.address)

    return LiquiditySnapshot.objects.create(
        token=token,
        timestamp=data.timestamp,
        pool_address=data.pool_address,
        liquidity_usd=data.liquidity_usd,
        liquidity_sol=data.liquidity_sol,
        lp_locked=data.lp_locked,
        lp_burned=data.lp_burned,
        is_mock=data.is_mock,
        source=data.source,
    )


def get_liquidity_features(token: Token) -> LiquidityFeatures | None:
    """Fetches the two most recent liquidity snapshots plus the latest
    market snapshot (for market cap and volume) and runs the liquidity
    feature extractor. Returns None if there's no liquidity snapshot yet."""
    snapshots = list(token.liquidity_snapshots.order_by("-timestamp")[:2])
    if not snapshots:
        return None

    current = snapshots[0]
    previous = snapshots[1] if len(snapshots) > 1 else None

    latest_market_snapshot = token.snapshots.order_by("-timestamp").first()
    market_cap = latest_market_snapshot.market_cap if latest_market_snapshot else None
    volume_5m = latest_market_snapshot.volume_5m if latest_market_snapshot else None

    return extract_liquidity_features(current, previous=previous, market_cap=market_cap, volume_5m=volume_5m)

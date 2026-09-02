from apps.holders.features import HolderFeatures, extract_holder_features
from apps.holders.models import HolderSnapshot
from apps.tokens.models import Token
from providers.registry import get_chain_provider


def collect_holders(token: Token) -> HolderSnapshot:
    """Fetch a current holder-distribution snapshot for `token` and store it."""
    provider = get_chain_provider()
    data = provider.get_holder_distribution(token.address)

    return HolderSnapshot.objects.create(
        token=token,
        timestamp=data.timestamp,
        holder_count=data.holder_count,
        top_holder_pct=data.top_holder_pct,
        top5_pct=data.top5_pct,
        top10_pct=data.top10_pct,
        creator_pct=data.creator_pct,
        insider_pct=data.insider_pct,
        is_mock=data.is_mock,
        source=data.source,
    )


def get_holder_features(token: Token) -> HolderFeatures | None:
    """Fetches the three most recent holder snapshots and runs the holder
    growth feature extractor. Returns None if there's no snapshot yet."""
    snapshots = list(token.holder_snapshots.order_by("-timestamp")[:3])
    if not snapshots:
        return None

    current = snapshots[0]
    previous = snapshots[1] if len(snapshots) > 1 else None
    earlier = snapshots[2] if len(snapshots) > 2 else None

    return extract_holder_features(current, previous=previous, earlier=earlier)

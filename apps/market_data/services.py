from apps.market_data.features import MarketFeatures, extract_market_features
from apps.market_data.models import TokenSnapshot
from apps.tokens.models import Token
from providers.registry import get_market_data_provider


def collect_market_data(token: Token) -> TokenSnapshot:
    """Fetch a current price/volume snapshot for `token` and store it. Also
    opportunistically backfills Token.description/website/social_links if
    the provider's response happened to include them and the token doesn't
    have them yet -- see Token.description's docstring for why this piggy-
    backs here instead of a dedicated fetch."""
    provider = get_market_data_provider()
    data = provider.get_market_snapshot(token.address)

    metadata_updates = {}
    if data.description and not token.description:
        metadata_updates["description"] = data.description
    if data.website and not token.website:
        metadata_updates["website"] = data.website
    if data.social_links and not token.social_links:
        metadata_updates["social_links"] = data.social_links
    if metadata_updates:
        Token.objects.filter(pk=token.pk).update(**metadata_updates)
        for field_name, value in metadata_updates.items():
            setattr(token, field_name, value)

    return TokenSnapshot.objects.create(
        token=token,
        timestamp=data.timestamp,
        price=data.price,
        market_cap=data.market_cap,
        volume_1m=data.volume_1m,
        volume_5m=data.volume_5m,
        volume_15m=data.volume_15m,
        volume_1h=data.volume_1h,
        buy_volume_5m=data.buy_volume_5m,
        sell_volume_5m=data.sell_volume_5m,
        unique_buyers_5m=data.unique_buyers_5m,
        unique_sellers_5m=data.unique_sellers_5m,
        is_mock=data.is_mock,
        source=data.source,
    )


def get_market_features(token: Token, *, history_size: int = 10) -> MarketFeatures | None:
    """Fetches the recent snapshot history for `token` and runs the
    market/momentum feature extractor against it. Returns None if there's
    no snapshot at all yet -- there's nothing to extract features from."""
    snapshots_desc = list(token.snapshots.order_by("-timestamp")[: history_size + 1])
    if not snapshots_desc:
        return None

    current = snapshots_desc[0]
    older_desc = snapshots_desc[1:]
    previous = older_desc[0] if older_desc else None
    history = list(reversed(older_desc))  # chronological oldest-to-newest, excludes `current`

    return extract_market_features(current, previous=previous, history=history)

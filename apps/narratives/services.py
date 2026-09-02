from django.utils import timezone

from apps.narratives.detection import TokenIdentityText, detect_narratives_for_token
from apps.narratives.models import Narrative, TokenNarrative
from apps.narratives.scoring import (
    CompetitionLevel,
    blend_with_social_signal,
    compute_narrative_competition,
    compute_narrative_momentum,
    compute_narrative_strength,
)
from apps.tokens.models import Token
from providers.registry import get_social_data_provider


def detect_token_narratives(token: Token) -> list[TokenNarrative]:
    """Runs narrative detection against `token`'s identity text and
    upserts a TokenNarrative row for every match at or above the relevance
    threshold. Existing links whose relevance has dropped are updated in
    place, not deleted -- a token that used to qualify and no longer does
    still has a real link with a low score, which is more honest than
    silently disappearing.
    """
    identity = TokenIdentityText(name=token.name, symbol=token.symbol, description=token.description)
    narratives = list(Narrative.objects.filter(is_active=True))
    matches = detect_narratives_for_token(identity, narratives)

    now = timezone.now()
    narratives_by_id = {n.id: n for n in narratives}
    links = []
    for match in matches:
        link, _ = TokenNarrative.objects.update_or_create(
            token=token,
            narrative=narratives_by_id[match.narrative_id],
            defaults={"relevance_score": match.relevance_score, "detected_at": now},
        )
        links.append(link)
    return links


def _narrative_aggregate_activity(narrative: Narrative) -> dict:
    active_links = TokenNarrative.objects.filter(narrative=narrative, token__is_active=True)
    token_ids = list(active_links.values_list("token_id", flat=True))

    from apps.market_data.models import TokenSnapshot

    latest_snapshot_by_token = {}
    for snapshot in (
        TokenSnapshot.objects.filter(token_id__in=token_ids).order_by("token_id", "-timestamp").iterator()
    ):
        latest_snapshot_by_token.setdefault(snapshot.token_id, snapshot)

    total_market_cap = sum(
        (s.market_cap for s in latest_snapshot_by_token.values() if s.market_cap), start=0
    )
    total_volume_5m = sum(
        (s.volume_5m for s in latest_snapshot_by_token.values() if s.volume_5m), start=0
    )

    return {
        "active_token_count": len(token_ids),
        "total_market_cap": total_market_cap or None,
        "total_volume_5m": total_volume_5m or None,
    }


def refresh_narrative_metrics(narrative: Narrative) -> dict:
    """Recomputes strength/momentum for `narrative` from current on-chain
    activity (blended with a social signal if a real provider is
    configured) and writes the same narrative-level values onto every
    active TokenNarrative row -- see the model's docstring for why that
    denormalization is the right shape for how the Token Detail page (PRD
    S41) actually consumes this data.
    """
    activity = _narrative_aggregate_activity(narrative)
    onchain_strength = compute_narrative_strength(
        active_token_count=activity["active_token_count"],
        total_market_cap=activity["total_market_cap"],
        total_volume_5m=activity["total_volume_5m"],
    )

    social_signal = get_social_data_provider().get_mention_signal(narrative.name)
    new_strength = blend_with_social_signal(onchain_strength, social_signal)

    active_links = TokenNarrative.objects.filter(narrative=narrative, token__is_active=True)
    existing = active_links.exclude(strength_score__isnull=True).first()
    previous_strength = existing.strength_score if existing else None
    momentum = compute_narrative_momentum(new_strength, previous_strength)

    active_links.update(strength_score=new_strength, momentum_score=momentum)

    return {
        "strength_score": new_strength,
        "momentum_score": momentum,
        "active_token_count": activity["active_token_count"],
    }


def rank_tokens_in_narrative(narrative: Narrative) -> list[TokenNarrative]:
    """Tokens in `narrative`, strongest candidate first (PRD S22: rank
    instead of alerting on every token in a crowded narrative)."""
    return list(
        TokenNarrative.objects.filter(narrative=narrative, token__is_active=True)
        .select_related("token")
        .order_by("-relevance_score")
    )


def get_narrative_competition(narrative: Narrative) -> CompetitionLevel:
    active_token_count = TokenNarrative.objects.filter(narrative=narrative, token__is_active=True).count()
    return compute_narrative_competition(active_token_count)

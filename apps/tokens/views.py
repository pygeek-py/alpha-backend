from django.http import Http404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.tokens.live_feed import DEFAULT_ORDERING
from apps.tokens.models import Token
from apps.tokens.serializers import LiveFeedRowSerializer, TokenDetailSerializer, TokenHistorySerializer
from apps.tokens.services import get_live_feed, get_token_detail, get_token_history


class LiveFeedView(APIView):
    """PRD S40: currently monitored tokens, sortable via ?ordering= and
    filterable via ?state=. Users should be able to sort and filter -- the
    query params ARE that UI, not a separate mechanism."""

    def get(self, request):
        ordering = request.query_params.get("ordering", DEFAULT_ORDERING)
        state = request.query_params.get("state") or None
        rows = get_live_feed(ordering=ordering, state=state)
        return Response(LiveFeedRowSerializer(rows, many=True).data)


class TokenDetailView(APIView):
    """PRD S41 Token Detail Page: overview, full score breakdown, narrative,
    outcome, and recent wallet activity in one payload."""

    def get(self, request, token_id: int):
        if not Token.objects.filter(pk=token_id).exists():
            raise Http404
        detail = get_token_detail(token_id)
        return Response(TokenDetailSerializer(detail).data)


class TokenHistoryView(APIView):
    """PRD S41's price/volume/holder-growth charts. ?hours= bounds the
    window (default 24h, matching the outcome-tracking horizon elsewhere in
    the project)."""

    def get(self, request, token_id: int):
        if not Token.objects.filter(pk=token_id).exists():
            raise Http404
        try:
            hours = int(request.query_params.get("hours", 24))
        except ValueError:
            hours = 24
        history = get_token_history(token_id, hours=hours)
        return Response(TokenHistorySerializer(history).data)

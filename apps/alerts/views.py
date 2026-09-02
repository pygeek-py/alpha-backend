from rest_framework.response import Response
from rest_framework.views import APIView

from apps.alerts.serializers import AlertRowSerializer
from apps.alerts.services import get_alerts


class AlertListView(APIView):
    """PRD S50/S57: the alert feed, newest first. ?state= filters to one
    alert state, ?priority_only=true filters to exceptional-opportunity
    alerts (PRD S35) only."""

    def get(self, request):
        state = request.query_params.get("state") or None
        priority_only = request.query_params.get("priority_only") == "true"
        rows = get_alerts(state=state, priority_only=priority_only)
        return Response(AlertRowSerializer(rows, many=True).data)

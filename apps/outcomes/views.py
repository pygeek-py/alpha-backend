from rest_framework.response import Response
from rest_framework.views import APIView

from apps.outcomes.serializers import PerformanceReportSerializer
from apps.outcomes.services import get_performance_report


class PerformanceView(APIView):
    """PRD S42 Historical Performance Dashboard."""

    def get(self, request):
        report = get_performance_report()
        return Response(PerformanceReportSerializer(report).data)

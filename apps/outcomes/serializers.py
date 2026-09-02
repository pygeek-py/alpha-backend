from rest_framework import serializers


class PerformanceSummarySerializer(serializers.Serializer):
    total_signals = serializers.IntegerField()
    completed_signals = serializers.IntegerField()
    hit_rate_2x_pct = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    hit_rate_3x_pct = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    hit_rate_5x_pct = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    avg_multiple = serializers.DecimalField(max_digits=10, decimal_places=4, allow_null=True)
    median_multiple = serializers.DecimalField(max_digits=10, decimal_places=4, allow_null=True)
    max_multiple = serializers.DecimalField(max_digits=10, decimal_places=4, allow_null=True)
    avg_time_to_2x_seconds = serializers.IntegerField(allow_null=True)
    avg_time_to_3x_seconds = serializers.IntegerField(allow_null=True)
    false_positive_rate_pct = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)


class BreakdownGroupSerializer(serializers.Serializer):
    label = serializers.CharField()
    total_signals = serializers.IntegerField()
    hit_rate_2x_pct = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    hit_rate_3x_pct = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)


class PerformanceReportSerializer(serializers.Serializer):
    summary = PerformanceSummarySerializer()
    by_narrative = BreakdownGroupSerializer(many=True)
    by_age = BreakdownGroupSerializer(many=True)
    by_score = BreakdownGroupSerializer(many=True)

from rest_framework import serializers


class AlertRowSerializer(serializers.Serializer):
    """PRD S50/S57 Alert feed row. Serializes the plain dicts
    apps/alerts/services.py's get_alerts assembles -- not a ModelSerializer,
    since each row is joined from Alert plus its token and (optionally)
    outcome, not one model."""

    id = serializers.IntegerField()
    token_id = serializers.IntegerField()
    token_symbol = serializers.CharField()
    token_address = serializers.CharField()
    state = serializers.CharField()
    score = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    risk_score = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    probability_2x = serializers.DecimalField(max_digits=5, decimal_places=4, allow_null=True)
    probability_3x = serializers.DecimalField(max_digits=5, decimal_places=4, allow_null=True)
    narrative_summary = serializers.CharField(allow_blank=True)
    reasons = serializers.ListField(child=serializers.CharField())
    is_priority = serializers.BooleanField()
    telegram_sent = serializers.BooleanField()
    telegram_sent_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()
    outcome_reached_2x = serializers.BooleanField(allow_null=True)
    outcome_reached_3x = serializers.BooleanField(allow_null=True)

from rest_framework import serializers

from apps.configuration.models import ConfigurationChange, SystemConfiguration


class SystemConfigurationSerializer(serializers.ModelSerializer):
    """Read-only view of the live config -- writes go through
    ConfigurationEvaluateView/ConfigurationApplyView, never a direct PATCH
    on values, since PRD S44 requires every manual change to be evaluated
    first."""

    class Meta:
        model = SystemConfiguration
        fields = [
            "min_liquidity_usd",
            "min_volume_5m_usd",
            "min_holder_count",
            "max_risk_score",
            "min_opportunity_score",
            "min_probability_2x",
            "min_probability_3x",
            "alert_cooldown_minutes",
            "max_alerts_per_hour",
            "autonomy_mode",
            "updated_at",
        ]
        read_only_fields = fields


class ThresholdRecommendationSerializer(serializers.Serializer):
    field_name = serializers.CharField()
    current_value = serializers.DecimalField(max_digits=24, decimal_places=6)
    recommended_value = serializers.DecimalField(max_digits=24, decimal_places=6)
    confidence = serializers.DecimalField(max_digits=6, decimal_places=2)
    sample_size = serializers.IntegerField()
    evidence_sufficient = serializers.BooleanField()
    reason = serializers.CharField()


class RecommendationReportSerializer(serializers.Serializer):
    thresholds = serializers.DictField(child=ThresholdRecommendationSerializer())
    overall_confidence = serializers.DecimalField(max_digits=6, decimal_places=2)
    notes = serializers.ListField(child=serializers.CharField())


class SimulationResultSerializer(serializers.Serializer):
    total_candidates = serializers.IntegerField()
    passing_count = serializers.IntegerField()
    pass_rate_pct = serializers.DecimalField(max_digits=6, decimal_places=2)
    avg_opportunity_score_passing = serializers.DecimalField(
        max_digits=6, decimal_places=2, allow_null=True
    )
    estimated_alerts_per_day = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    estimated_2x_hit_rate = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    estimated_3x_hit_rate = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    estimated_false_positive_rate = serializers.DecimalField(
        max_digits=6, decimal_places=2, allow_null=True
    )


class ConfigurationAssessmentSerializer(serializers.Serializer):
    recommendation_score = serializers.DecimalField(max_digits=6, decimal_places=2)
    verdict = serializers.CharField()
    changed_fields = serializers.ListField(child=serializers.CharField())
    expected_effects = serializers.ListField(child=serializers.CharField())
    field_notes = serializers.ListField(child=serializers.CharField())


class ConfigurationChangeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConfigurationChange
        fields = [
            "id",
            "previous_config",
            "new_config",
            "changed_fields",
            "reason",
            "expected_improvement",
            "actual_improvement",
            "change_source",
            "model_version",
            "created_at",
        ]

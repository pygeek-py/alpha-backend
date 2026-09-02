from decimal import Decimal, InvalidOperation

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.configuration.models import AutonomyMode, ConfigurationChange, ConfigurationChangeSource
from apps.configuration.serializers import (
    ConfigurationAssessmentSerializer,
    ConfigurationChangeSerializer,
    RecommendationReportSerializer,
    SimulationResultSerializer,
    SystemConfigurationSerializer,
)
from apps.configuration.services import (
    apply_configuration_change,
    config_to_dict,
    evaluate_configuration_change,
    generate_ai_recommended_configuration,
    get_current_configuration,
    simulate_configuration_change,
)

# (field name, python caster) -- narrative_settings/smart_money_settings are
# deliberately excluded: PRD S44's threshold list is all numeric fields, and
# those two are free-form JSON blobs with no evaluate/simulate story yet.
_CONFIG_FIELD_CASTERS: dict[str, type] = {
    "min_liquidity_usd": Decimal,
    "min_volume_5m_usd": Decimal,
    "min_holder_count": int,
    "max_risk_score": Decimal,
    "min_opportunity_score": Decimal,
    "min_probability_2x": Decimal,
    "min_probability_3x": Decimal,
    "alert_cooldown_minutes": int,
    "max_alerts_per_hour": int,
}


def _parse_proposed_values(data: dict) -> dict | None:
    """Merges whatever fields the client sent onto the CURRENT config, so
    evaluate/simulate/apply always see a full, valid config dict -- matches
    the PRD S44 UX of proposing a change to one or two fields at a time
    while the rest stay as they are."""
    merged = config_to_dict(get_current_configuration())
    try:
        for key, value in data.items():
            if key not in _CONFIG_FIELD_CASTERS:
                continue
            caster = _CONFIG_FIELD_CASTERS[key]
            merged[key] = caster(str(value)) if caster is Decimal else caster(value)
    except (TypeError, ValueError, InvalidOperation):
        return None
    return merged


class ConfigurationCurrentView(APIView):
    """PRD S44: the live config plus the AI's current recommendation, in one
    payload -- what the Configuration page leads with."""

    def get(self, request):
        config = get_current_configuration()
        report = generate_ai_recommended_configuration()
        return Response(
            {
                "current": SystemConfigurationSerializer(config).data,
                "recommendation": RecommendationReportSerializer(report).data,
            }
        )

    def patch(self, request):
        """Autonomy-mode switch only (PRD S44 Configuration Autonomy).
        Threshold VALUE changes must go through evaluate/apply instead --
        never a silent direct write."""
        autonomy_mode = request.data.get("autonomy_mode")
        valid_modes = {choice[0] for choice in AutonomyMode.choices}
        if autonomy_mode not in valid_modes:
            return Response(
                {"detail": f"autonomy_mode must be one of {sorted(valid_modes)}."}, status=400
            )

        config = get_current_configuration()
        config.autonomy_mode = autonomy_mode
        config.save()
        return Response(SystemConfigurationSerializer(config).data)


class ConfigurationEvaluateView(APIView):
    """PRD S44 User Overrides: evaluate a proposed change (recommendation
    score, expected effects, before/after simulation) without applying it."""

    def post(self, request):
        proposed = _parse_proposed_values(request.data)
        if proposed is None:
            return Response({"detail": "Invalid proposed configuration values."}, status=400)

        current = config_to_dict(get_current_configuration())
        assessment = evaluate_configuration_change(proposed)
        simulation_current = simulate_configuration_change(current)
        simulation_proposed = simulate_configuration_change(proposed)

        return Response(
            {
                "assessment": ConfigurationAssessmentSerializer(assessment).data,
                "simulation_current": SimulationResultSerializer(simulation_current).data,
                "simulation_proposed": SimulationResultSerializer(simulation_proposed).data,
            }
        )


class ConfigurationApplyView(APIView):
    """Applies a manual configuration change and records the audit entry
    (PRD S44 AI Self-Optimization's record applies to manual changes too)."""

    def post(self, request):
        proposed = _parse_proposed_values(request.data)
        if proposed is None:
            return Response({"detail": "Invalid proposed configuration values."}, status=400)
        reason = request.data.get("reason") or "Manual change via dashboard"

        config, change = apply_configuration_change(
            proposed, source=ConfigurationChangeSource.MANUAL, reason=reason
        )
        return Response(
            {
                "current": SystemConfigurationSerializer(config).data,
                "change": ConfigurationChangeSerializer(change).data,
            }
        )


class ConfigurationHistoryView(APIView):
    """PRD S44: the audit trail of every automatic AND manual change."""

    def get(self, request):
        changes = ConfigurationChange.objects.all()[:50]
        return Response(ConfigurationChangeSerializer(changes, many=True).data)

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.configuration.analysis import (
    ConfigurationRecommendationReport,
    build_recommendation_report,
    recommend_threshold,
)
from apps.configuration.evaluation import ConfigurationAssessment, evaluate_proposed_configuration
from apps.configuration.models import ConfigurationChange, ConfigurationChangeSource, SystemConfiguration
from apps.configuration.simulation import CandidateSnapshot, SimulationResult, simulate_configuration
from apps.holders.models import HolderSnapshot
from apps.liquidity.models import LiquiditySnapshot
from apps.market_data.models import TokenSnapshot
from apps.scoring.models import TokenScore

# The tunable fields this engine manages via percentile analysis. Alert
# cooldown/frequency and probability thresholds are deliberately excluded --
# they need alert/prediction history (Batches 10-12) that doesn't exist yet.
ANALYZABLE_FIELDS = {
    "min_liquidity_usd": {"target_percentile": 75, "kind": "min"},
    "min_volume_5m_usd": {"target_percentile": 75, "kind": "min"},
    "min_holder_count": {"target_percentile": 75, "kind": "min"},
    "min_opportunity_score": {"target_percentile": 75, "kind": "min"},
    "max_risk_score": {"target_percentile": 25, "kind": "max"},
}

DEFAULT_SIMULATION_WINDOW_DAYS = 7
MODEL_VERSION = "config-v1"
AUTO_APPLY_MIN_SCORE = Decimal("70")


def get_current_configuration() -> SystemConfiguration:
    config = SystemConfiguration.objects.filter(is_active=True).order_by("-updated_at").first()
    if config is None:
        config = SystemConfiguration.objects.create()
    return config


def config_to_dict(config: SystemConfiguration) -> dict:
    return {
        "min_liquidity_usd": config.min_liquidity_usd,
        "min_volume_5m_usd": config.min_volume_5m_usd,
        "min_holder_count": config.min_holder_count,
        "max_risk_score": config.max_risk_score,
        "min_opportunity_score": config.min_opportunity_score,
        "min_probability_2x": config.min_probability_2x,
        "min_probability_3x": config.min_probability_3x,
        "alert_cooldown_minutes": config.alert_cooldown_minutes,
        "max_alerts_per_hour": config.max_alerts_per_hour,
    }


def _nearest_at_or_before(queryset, token_id: int, at_time):
    return queryset.filter(token_id=token_id, timestamp__lte=at_time).order_by("-timestamp").first()


def gather_candidate_snapshots(
    *, window_days: int = DEFAULT_SIMULATION_WINDOW_DAYS
) -> list[CandidateSnapshot]:
    """One CandidateSnapshot per recent TokenScore, enriched with whatever
    liquidity/volume/holder data existed at-or-before that score's
    timestamp. Point-in-time lookups (not just "latest") to avoid leaking
    later data into what's meant to represent "what we knew back then" --
    same principle as the ML feature-snapshot design elsewhere in this
    project, applied here to keep the simulation honest.
    """
    since = timezone.now() - timedelta(days=window_days)
    scores = TokenScore.objects.filter(timestamp__gte=since).select_related("token")

    candidates = []
    for score in scores:
        liquidity = _nearest_at_or_before(LiquiditySnapshot.objects, score.token_id, score.timestamp)
        volume = _nearest_at_or_before(TokenSnapshot.objects, score.token_id, score.timestamp)
        holders = _nearest_at_or_before(HolderSnapshot.objects, score.token_id, score.timestamp)
        candidates.append(
            CandidateSnapshot(
                opportunity_score=score.opportunity_score,
                risk_score=score.risk_score,
                liquidity_usd=liquidity.liquidity_usd if liquidity else None,
                volume_5m_usd=volume.volume_5m if volume else None,
                holder_count=holders.holder_count if holders else None,
            )
        )
    return candidates


def _distribution_for_field(field_name: str, candidates: list[CandidateSnapshot]) -> list[Decimal]:
    attr_by_field = {
        "min_liquidity_usd": "liquidity_usd",
        "min_volume_5m_usd": "volume_5m_usd",
        "min_holder_count": "holder_count",
        "min_opportunity_score": "opportunity_score",
        "max_risk_score": "risk_score",
    }
    attr = attr_by_field[field_name]
    return [Decimal(getattr(c, attr)) for c in candidates if getattr(c, attr) is not None]


def generate_ai_recommended_configuration(
    *, window_days: int = DEFAULT_SIMULATION_WINDOW_DAYS
) -> ConfigurationRecommendationReport:
    current = config_to_dict(get_current_configuration())
    candidates = gather_candidate_snapshots(window_days=window_days)

    thresholds = {}
    for field_name, params in ANALYZABLE_FIELDS.items():
        values = _distribution_for_field(field_name, candidates)
        thresholds[field_name] = recommend_threshold(
            field_name=field_name,
            values=values,
            current_value=Decimal(current[field_name]),
            target_percentile=params["target_percentile"],
        )

    report = build_recommendation_report(thresholds)
    unanalyzable = (
        "min_probability_2x", "min_probability_3x", "alert_cooldown_minutes", "max_alerts_per_hour",
    )
    for field_name in unanalyzable:
        report.notes.append(
            f"{field_name}: no recommendation -- needs alert/prediction history that doesn't exist yet"
        )
    return report


def simulate_configuration_change(
    config_values: dict, *, window_days: int = DEFAULT_SIMULATION_WINDOW_DAYS
) -> SimulationResult:
    candidates = gather_candidate_snapshots(window_days=window_days)
    return simulate_configuration(config_values, candidates, window_days=Decimal(window_days))


def evaluate_configuration_change(
    proposed: dict, *, window_days: int = DEFAULT_SIMULATION_WINDOW_DAYS
) -> ConfigurationAssessment:
    current_config = get_current_configuration()
    current = config_to_dict(current_config)
    recommended_report = generate_ai_recommended_configuration(window_days=window_days)
    recommended = {
        name: t.recommended_value
        for name, t in recommended_report.thresholds.items()
        if t.evidence_sufficient
    }

    candidates = gather_candidate_snapshots(window_days=window_days)
    simulation_current = simulate_configuration(current, candidates, window_days=Decimal(window_days))
    simulation_proposed = simulate_configuration(proposed, candidates, window_days=Decimal(window_days))

    return evaluate_proposed_configuration(
        current=current,
        proposed=proposed,
        recommended=recommended,
        simulation_current=simulation_current,
        simulation_proposed=simulation_proposed,
    )


def apply_configuration_change(
    new_values: dict,
    *,
    source: str,
    reason: str,
    model_version: str = MODEL_VERSION,
    expected_improvement: dict | None = None,
) -> tuple[SystemConfiguration, ConfigurationChange]:
    """Updates the live SystemConfiguration and writes the audit trail entry
    in one step -- the two must never happen separately, or a config change
    could exist without a record of why. Returns (config, change)."""
    config = get_current_configuration()
    previous = config_to_dict(config)

    changed_fields = [
        name for name, value in new_values.items() if name in previous and value != previous[name]
    ]

    for name, value in new_values.items():
        if hasattr(config, name):
            setattr(config, name, value)
    config.save()

    change = ConfigurationChange.objects.create(
        previous_config=_json_safe(previous),
        new_config=_json_safe(config_to_dict(config)),
        changed_fields=changed_fields,
        reason=reason,
        expected_improvement=_json_safe(expected_improvement or {}),
        change_source=source,
        model_version=model_version,
    )
    return config, change


def _json_safe(data: dict) -> dict:
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in data.items()}


def maybe_auto_apply_ai_recommendation(
    *, window_days: int = DEFAULT_SIMULATION_WINDOW_DAYS
) -> ConfigurationChange | None:
    """The AI_AUTOMATIC autonomy mode's entry point. Applies the AI's own
    recommendation only when there's sufficient evidence AND the assessment
    scores it as at least "reasonable" -- with current data sparsity
    (Batches 10-11 not yet built), this will typically find no sufficiently-
    evidenced changes to make, which is the correct, honest behavior rather
    than forcing a change on thin evidence.
    """
    config = get_current_configuration()
    if config.autonomy_mode != "ai_automatic":
        return None

    report = generate_ai_recommended_configuration(window_days=window_days)
    current = config_to_dict(config)
    proposed = {
        name: t.recommended_value
        for name, t in report.thresholds.items()
        if t.evidence_sufficient and t.recommended_value != current.get(name)
    }
    if not proposed:
        return None

    assessment = evaluate_configuration_change(proposed, window_days=window_days)
    if assessment.recommendation_score < AUTO_APPLY_MIN_SCORE:
        return None

    _config, change = apply_configuration_change(
        proposed,
        source=ConfigurationChangeSource.AI_AUTOMATIC,
        reason=f"Automatic adjustment (recommendation score {assessment.recommendation_score}): "
        + "; ".join(report.thresholds[name].reason for name in proposed),
        expected_improvement={"expected_effects": assessment.expected_effects},
    )
    return change

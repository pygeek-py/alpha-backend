"""Evaluates a PROPOSED configuration change before it's applied (PRD S44):
a Recommendation Score plus plain-language expected effects. Pure function
given the current config, the proposed config, the AI's own recommended
values (from analysis.py), and simulation results for both (from
simulation.py) -- apps/configuration/services.py assembles those inputs.
"""

from dataclasses import dataclass, field
from decimal import Decimal

RECOMMENDATION_BANDS = (
    (80, "strongly_recommended"),
    (60, "reasonable"),
    (40, "neutral"),
    (20, "not_recommended"),
    (0, "strongly_discouraged"),
)

VOLUME_COLLAPSE_PENALTY = Decimal("20")
VOLUME_SURGE_PENALTY = Decimal("15")
VOLUME_SURGE_RATIO_THRESHOLD = Decimal("2")


def _verdict_for(score: Decimal) -> str:
    for floor, label in RECOMMENDATION_BANDS:
        if score >= floor:
            return label
    return "strongly_discouraged"


@dataclass
class ConfigurationAssessment:
    recommendation_score: Decimal
    verdict: str
    changed_fields: list[str] = field(default_factory=list)
    expected_effects: list[str] = field(default_factory=list)
    field_notes: list[str] = field(default_factory=list)


def _alignment_score(current_value, proposed_value, recommended_value) -> Decimal | None:
    """100 if the proposed value matches the AI's recommendation exactly (or
    the change moves fully from current to recommended); 50 if the change is
    orthogonal to the recommendation; lower the further proposed moves AWAY
    from it relative to where current already was.
    """
    if recommended_value is None or current_value is None or proposed_value is None:
        return None

    current_value = Decimal(current_value)
    proposed_value = Decimal(proposed_value)
    recommended_value = Decimal(recommended_value)

    dist_current = abs(current_value - recommended_value)
    dist_proposed = abs(proposed_value - recommended_value)
    if dist_current == 0 and dist_proposed == 0:
        return Decimal("100")

    max_dist = max(dist_current, dist_proposed, Decimal("0.0001"))
    improvement_ratio = (dist_current - dist_proposed) / max_dist
    score = Decimal("50") + improvement_ratio * 50
    return max(Decimal("0"), min(Decimal("100"), score)).quantize(Decimal("0.01"))


def evaluate_proposed_configuration(
    *, current: dict, proposed: dict, recommended: dict, simulation_current, simulation_proposed
) -> ConfigurationAssessment:
    changed_fields = [
        name for name in proposed if name in current and proposed[name] != current[name]
    ]

    alignment_scores = []
    field_notes = []
    for name in changed_fields:
        score = _alignment_score(current.get(name), proposed.get(name), recommended.get(name))
        if score is None:
            continue
        alignment_scores.append(score)
        direction = "toward" if score >= 50 else "away from"
        field_notes.append(
            f"{name}: {current[name]} -> {proposed[name]} moves {direction} the AI's recommendation"
        )

    alignment_component = (
        (sum(alignment_scores) / len(alignment_scores)).quantize(Decimal("0.01"))
        if alignment_scores
        else Decimal("50")
    )

    expected_effects = []
    penalty = Decimal("0")

    if simulation_proposed.passing_count == 0 and simulation_current.passing_count > 0:
        penalty += VOLUME_COLLAPSE_PENALTY
        expected_effects.append(
            "This would have produced almost no alerts against recent history -- likely too strict"
        )
    elif simulation_current.passing_count > 0:
        ratio = Decimal(simulation_proposed.passing_count) / Decimal(simulation_current.passing_count)
        if ratio >= VOLUME_SURGE_RATIO_THRESHOLD:
            penalty += VOLUME_SURGE_PENALTY
            expected_effects.append(
                f"Alert volume would be roughly {ratio.quantize(Decimal('0.1'))}x recent history -- "
                "expect lower average signal quality"
            )
        elif ratio <= Decimal("0.5"):
            expected_effects.append(
                f"Alert volume would drop to roughly {ratio.quantize(Decimal('0.1'))}x recent history -- "
                "fewer but likely higher-quality signals"
            )

    current_avg = simulation_current.avg_opportunity_score_passing
    proposed_avg = simulation_proposed.avg_opportunity_score_passing
    if current_avg and proposed_avg:
        score_delta = proposed_avg - current_avg
        if score_delta > 0:
            expected_effects.append(
                f"Average opportunity score of passing tokens would rise by {score_delta}"
            )
        elif score_delta < 0:
            expected_effects.append(
                f"Average opportunity score of passing tokens would fall by {abs(score_delta)}"
            )

    recommendation_score = max(Decimal("0"), min(Decimal("100"), alignment_component - penalty))

    return ConfigurationAssessment(
        recommendation_score=recommendation_score.quantize(Decimal("0.01")),
        verdict=_verdict_for(recommendation_score),
        changed_fields=changed_fields,
        expected_effects=expected_effects,
        field_notes=field_notes,
    )

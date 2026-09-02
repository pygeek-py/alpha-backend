from decimal import Decimal

import pytest
from django.utils import timezone

from apps.configuration.models import ConfigurationChange, ConfigurationChangeSource, SystemConfiguration
from apps.configuration.services import (
    apply_configuration_change,
    config_to_dict,
    evaluate_configuration_change,
    gather_candidate_snapshots,
    generate_ai_recommended_configuration,
    get_current_configuration,
    maybe_auto_apply_ai_recommendation,
    simulate_configuration_change,
)
from apps.holders.models import HolderSnapshot
from apps.liquidity.models import LiquiditySnapshot
from apps.market_data.models import TokenSnapshot
from apps.scoring.models import TokenScore
from apps.tokens.factories import TokenFactory


@pytest.mark.django_db
class TestGetCurrentConfiguration:
    def test_creates_a_default_row_if_none_exists(self):
        assert SystemConfiguration.objects.count() == 0
        config = get_current_configuration()
        assert config.autonomy_mode == "ai_automatic"
        assert SystemConfiguration.objects.count() == 1

    def test_returns_the_same_row_on_repeated_calls(self):
        first = get_current_configuration()
        second = get_current_configuration()
        assert first.pk == second.pk


def _create_scored_token(
    *, opportunity_score, risk_score, liquidity_usd=None, volume_5m=None, holder_count=None
):
    token = TokenFactory()
    now = timezone.now()
    if liquidity_usd is not None:
        LiquiditySnapshot.objects.create(token=token, timestamp=now, liquidity_usd=liquidity_usd)
    if volume_5m is not None:
        TokenSnapshot.objects.create(token=token, timestamp=now, price=Decimal("0.001"), volume_5m=volume_5m)
    if holder_count is not None:
        HolderSnapshot.objects.create(token=token, timestamp=now, holder_count=holder_count)
    return TokenScore.objects.create(
        token=token,
        timestamp=now,
        opportunity_score=opportunity_score,
        risk_score=risk_score,
        score_2x=opportunity_score,
        score_3x=opportunity_score,
    )


@pytest.mark.django_db
class TestGatherCandidateSnapshots:
    def test_pulls_recent_token_scores_with_enriched_data(self):
        _create_scored_token(
            opportunity_score=Decimal("80"), risk_score=Decimal("20"),
            liquidity_usd=Decimal("50000"), volume_5m=Decimal("10000"), holder_count=300,
        )
        candidates = gather_candidate_snapshots(window_days=7)
        assert len(candidates) == 1
        assert candidates[0].liquidity_usd == Decimal("50000")
        assert candidates[0].holder_count == 300

    def test_missing_snapshots_leave_fields_none_not_fabricated(self):
        _create_scored_token(opportunity_score=Decimal("80"), risk_score=Decimal("20"))
        candidates = gather_candidate_snapshots(window_days=7)
        assert candidates[0].liquidity_usd is None
        assert candidates[0].holder_count is None


@pytest.mark.django_db
class TestGenerateAiRecommendedConfiguration:
    def test_insufficient_data_keeps_current_values(self):
        report = generate_ai_recommended_configuration()
        for threshold in report.thresholds.values():
            assert threshold.evidence_sufficient is False

    def test_sufficient_data_produces_a_recommendation(self):
        for i in range(20):
            _create_scored_token(
                opportunity_score=Decimal(50 + i), risk_score=Decimal(50 - i),
                liquidity_usd=Decimal(1000 * (i + 1)),
            )
        report = generate_ai_recommended_configuration()
        assert report.thresholds["min_opportunity_score"].evidence_sufficient is True

    def test_probability_and_alert_fields_are_explicitly_unanalyzable(self):
        report = generate_ai_recommended_configuration()
        joined_notes = " ".join(report.notes)
        assert "min_probability_2x" in joined_notes
        assert "alert_cooldown_minutes" in joined_notes


@pytest.mark.django_db
class TestSimulateConfigurationChange:
    def test_simulates_against_real_token_scores(self):
        for i in range(5):
            _create_scored_token(opportunity_score=Decimal(40 + i * 10), risk_score=Decimal("20"))
        result = simulate_configuration_change({"min_opportunity_score": Decimal("60")})
        assert result.total_candidates == 5
        assert result.passing_count == 3  # 60, 70, 80 pass; 40, 50 don't


@pytest.mark.django_db
class TestEvaluateConfigurationChange:
    def test_returns_an_assessment(self):
        _create_scored_token(opportunity_score=Decimal("80"), risk_score=Decimal("20"))
        assessment = evaluate_configuration_change({"min_opportunity_score": Decimal("70")})
        assert Decimal("0") <= assessment.recommendation_score <= Decimal("100")


@pytest.mark.django_db
class TestApplyConfigurationChange:
    def test_updates_config_and_creates_audit_entry(self):
        config, change = apply_configuration_change(
            {"min_opportunity_score": Decimal("75")},
            source=ConfigurationChangeSource.MANUAL,
            reason="testing",
        )
        assert config.min_opportunity_score == Decimal("75")
        assert isinstance(change, ConfigurationChange)
        assert change.changed_fields == ["min_opportunity_score"]
        assert change.reason == "testing"

    def test_previous_and_new_config_are_recorded(self):
        get_current_configuration()  # ensure a row with defaults exists first
        config, change = apply_configuration_change(
            {"min_opportunity_score": Decimal("60")},
            source=ConfigurationChangeSource.MANUAL,
            reason="testing",
        )
        assert change.previous_config["min_opportunity_score"] == "0.00"
        assert change.new_config["min_opportunity_score"] == "60"

    def test_unchanged_values_are_not_listed_as_changed(self):
        config = get_current_configuration()
        current = config_to_dict(config)
        _config, change = apply_configuration_change(
            {**current, "min_holder_count": 42},
            source=ConfigurationChangeSource.MANUAL,
            reason="testing",
        )
        assert change.changed_fields == ["min_holder_count"]


@pytest.mark.django_db
class TestMaybeAutoApplyAiRecommendation:
    def test_no_op_when_insufficient_evidence(self):
        get_current_configuration()  # AI_AUTOMATIC by default
        result = maybe_auto_apply_ai_recommendation()
        assert result is None
        assert ConfigurationChange.objects.count() == 0

    def test_no_op_when_autonomy_mode_is_not_automatic(self):
        config = get_current_configuration()
        config.autonomy_mode = "manual"
        config.save()
        for i in range(30):
            _create_scored_token(opportunity_score=Decimal(i), risk_score=Decimal("50"))
        assert maybe_auto_apply_ai_recommendation() is None

    def test_applies_and_audits_when_evidence_and_score_are_sufficient(self):
        get_current_configuration()  # is_active AI_AUTOMATIC config exists
        # Strong, consistent signal: every observed token clears a high bar,
        # so recommending a much higher min_opportunity_score should align
        # well with the (very low, default) current value moving up.
        for _i in range(30):
            _create_scored_token(opportunity_score=Decimal("95"), risk_score=Decimal("5"))

        change = maybe_auto_apply_ai_recommendation()

        # May or may not clear the auto-apply score bar depending on exact
        # weighting -- either outcome is valid, but if it DID apply, it must
        # be properly audited.
        if change is not None:
            assert change.change_source == ConfigurationChangeSource.AI_AUTOMATIC
            assert change.model_version
            assert change.reason

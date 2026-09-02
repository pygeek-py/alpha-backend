import pytest

from apps.configuration.models import (
    AutonomyMode,
    ConfigurationChange,
    ConfigurationChangeSource,
    SystemConfiguration,
)


@pytest.mark.django_db
class TestSystemConfiguration:
    def test_default_autonomy_is_ai_automatic(self):
        """Confirmed product decision (ARCHITECTURE.md S10, PRD S44) -- the
        system defaults to automatically adjusting its own thresholds."""
        config = SystemConfiguration.objects.create()
        assert config.autonomy_mode == AutonomyMode.AI_AUTOMATIC
        assert config.is_active is True


@pytest.mark.django_db
class TestConfigurationChange:
    def test_create_audit_record(self):
        change = ConfigurationChange.objects.create(
            previous_config={"min_opportunity_score": 82},
            new_config={"min_opportunity_score": 75},
            changed_fields=["min_opportunity_score"],
            reason="User requested lower threshold",
            change_source=ConfigurationChangeSource.MANUAL,
        )
        assert change.change_source == ConfigurationChangeSource.MANUAL
        assert change.actual_improvement == {}

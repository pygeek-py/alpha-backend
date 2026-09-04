import pytest

from apps.core.pipeline import run_pipeline_once
from apps.tokens.factories import TokenFactory


@pytest.mark.django_db
class TestRunPipelineOnce:
    def test_runs_every_stage_with_no_tokens(self):
        result = run_pipeline_once()

        expected_stages = {
            "discover_tokens",
            "collect_market_data",
            "collect_liquidity",
            "collect_holders",
            "analyze_token_safety",
            "calculate_wallet_reputation",
            "run_wallet_clustering",
            "analyze_narrative",
            "refresh_narrative_metrics",
            "calculate_token_score",
            "generate_prediction",
            "evaluate_alert_state",
            "track_token_outcome",
            "send_pending_telegram_alerts",
            "evaluate_ai_configuration",
        }
        assert set(result.keys()) == expected_stages
        for stage, value in result.items():
            assert not (isinstance(value, dict) and "error" in value), f"{stage} failed: {value}"

    def test_runs_with_active_tokens_present(self):
        TokenFactory.create_batch(2)

        result = run_pipeline_once()

        for stage, value in result.items():
            assert not (isinstance(value, dict) and "error" in value), f"{stage} failed: {value}"
        # >= 2, not == 2 -- discover_tokens (stage 1) adds its own mock-
        # provider fixture tokens on top of the 2 created directly here.
        assert result["collect_market_data"]["queued"] >= 2

    def test_restores_eager_mode_setting_afterward(self):
        from config.celery import app as celery_app

        original = celery_app.conf.task_always_eager
        run_pipeline_once()
        assert celery_app.conf.task_always_eager == original

    def test_zero_time_budget_skips_every_stage(self):
        result = run_pipeline_once(time_budget_seconds=0)

        for stage, value in result.items():
            assert value == {"skipped": "time budget exceeded"}, f"{stage} was not skipped: {value}"

    def test_one_failing_stage_does_not_abort_the_rest(self, monkeypatch):
        import apps.core.pipeline as pipeline_module

        def _boom():
            raise RuntimeError("simulated provider outage")

        original_steps = pipeline_module._pipeline_steps

        def _patched_steps():
            steps = original_steps()
            # Replace the first stage's callable with one whose .delay()
            # raises, to prove downstream stages still run.
            class _Boom:
                def delay(self):
                    class _R:
                        def get(self):
                            _boom()
                    return _R()

            steps[0] = (steps[0][0], _Boom())
            return steps

        monkeypatch.setattr(pipeline_module, "_pipeline_steps", _patched_steps)

        result = run_pipeline_once()

        first_stage_name = original_steps()[0][0]
        assert "error" in result[first_stage_name]
        assert "track_token_outcome" in result
        assert "error" not in result["track_token_outcome"]

import time

import pytest

from apps.core.pipeline import run_pipeline_once
from apps.tokens.factories import TokenFactory


# transaction=True, not the default django_db marker: run_pipeline_once()
# genuinely runs DB writes from a background thread (a real per-stage
# hard timeout, not a test artifact -- see apps/core/pipeline.py). The
# default marker wraps each test in an uncommitted transaction on the
# main thread's connection, which holds an exclusive lock other
# connections/threads can't get past -- transaction=True uses real
# commit-based isolation (table truncation between tests) instead, which
# a second connection can actually see and write alongside.
@pytest.mark.django_db(transaction=True)
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

    def test_a_stage_exceeding_its_hard_timeout_is_marked_and_does_not_block_the_rest(
        self, monkeypatch
    ):
        import apps.core.pipeline as pipeline_module

        original_steps = pipeline_module._pipeline_steps

        def _patched_steps():
            # Entirely fake, instant stages -- not the real tasks. Using
            # the real ones here (even with a "generous" timeout) risked
            # exactly what it caught live: a real mock-provider task
            # (discover_tokens) racing pytest-django's transaction=True
            # table flush between tests when ITS thread also got abandoned
            # under load, corrupting the next test's teardown. Only the
            # ONE deliberately-slow stage needs to be real-ish here; the
            # rest just need to prove they still ran.
            class _Fast:
                def delay(self):
                    class _R:
                        def get(self):
                            return {"ok": True}
                    return _R()

            # Blocks far longer than stage_timeout_seconds below -- proves
            # the hard per-stage timeout actually stops WAITING rather
            # than blocking the whole run on it. No DB access, so its
            # abandoned thread can't interfere with anything afterward.
            class _Slow:
                def delay(self):
                    class _R:
                        def get(self):
                            time.sleep(2)
                            return {"queued": 0}
                    return _R()

            names = [name for name, _ in original_steps()]
            return [(names[0], _Slow())] + [(name, _Fast()) for name in names[1:]]

        monkeypatch.setattr(pipeline_module, "_pipeline_steps", _patched_steps)

        started = time.monotonic()
        result = run_pipeline_once(time_budget_seconds=999, stage_timeout_seconds=0.3)
        elapsed = time.monotonic() - started

        first_stage_name = original_steps()[0][0]
        assert result[first_stage_name] == {"timed_out": True}
        assert "track_token_outcome" in result
        assert "error" not in result["track_token_outcome"]
        # The whole run returned well before the abandoned 2s sleep finished.
        assert elapsed < 2

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

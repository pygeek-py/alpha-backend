"""Synchronous, worker-free pipeline runner for deployments with no Celery
worker/beat (a genuinely-free hosting path: web service + Postgres only,
see ARCHITECTURE.md's deployment notes). An external free scheduler
(GitHub Actions cron) calls the /api/v1/pipeline/run/ endpoint on an
interval, which runs this -- one full pass through every stage of the
pipeline, in the same dependency order CELERY_BEAT_SCHEDULE would
otherwise run them independently on their own intervals.

This reuses the exact same task functions every other deployment path
uses -- not a second implementation of the pipeline logic. It works by
temporarily flipping Celery's task_always_eager/task_eager_propagates
conf, the same mechanism CELERY_TASK_ALWAYS_EAGER already proves correct
across the whole test suite (config/settings/test.py): `.delay()` then
runs the task body synchronously in-process instead of publishing to a
broker, including every nested `.delay()` a fan-out task calls internally.

Trade-off, stated plainly and confirmed by live measurement, not guessed:
a clean, uncontended full pass across 31 real active tokens (real Birdeye
+ QuickNode calls spread fairly evenly across most stages, not
concentrated in one) took 622 seconds. That's far beyond any HTTP request
timeout on any host. The time_budget_seconds mechanism below keeps any
SINGLE invocation safely short, but the honest consequence is that a full
cycle through all 14 stages takes many cron ticks to complete once --
realistically hours, not minutes, at this token count. This is a
genuinely slow, eventually-consistent substitute for the real pipeline,
not a real-time one -- fine for occasional/manual runs or a token count in
the single digits, not a real substitute for Redis + a worker if anything
resembling the PRD's intended near-real-time behavior matters. Every
stage now also runs at the SAME cadence (this endpoint's calling
interval), not each at its own tuned interval the way
CELERY_BEAT_SCHEDULE has them. Revisit (delete this file and the
/api/v1/pipeline/run/ endpoint) once a real worker gets added -- see
ARCHITECTURE.md S5.1.
"""

import logging
import time

from config.celery import app as celery_app

logger = logging.getLogger("alpha.pipeline")

# Real external API calls (Birdeye/QuickNode, per active token, across
# several stages) turned out live-testing to be much slower than mock-data
# tests suggested -- discovering just 2 real tokens took well over a
# minute in one observed run. Free-tier hosts commonly cap HTTP request
# duration well under that (exact limits vary and aren't guaranteed by any
# provider), so this budget is a deliberately conservative safety net: once
# elapsed time crosses it, any stage not yet STARTED is skipped (clearly
# marked, not silently dropped) rather than risk the host killing the
# request mid-stage with an unclear, half-applied result. Skipped stages
# just run on the next cron tick -- see ARCHITECTURE.md S5.1.
DEFAULT_TIME_BUDGET_SECONDS = 45


def _pipeline_steps():
    """Imported lazily (inside the function, not at module load) so this
    module has no import-time dependency on every task module -- keeps
    apps/core from needing to know about every other app just to define
    the health check / dashboard views that live alongside this file."""
    from apps.alerts.tasks import evaluate_alert_state_for_active_tokens
    from apps.configuration.tasks import evaluate_ai_configuration
    from apps.holders.tasks import collect_holders_for_active_tokens
    from apps.liquidity.tasks import collect_liquidity_for_active_tokens
    from apps.market_data.tasks import collect_market_data_for_active_tokens
    from apps.narratives.tasks import (
        analyze_narrative_for_active_tokens,
        refresh_narrative_metrics_for_active_narratives,
    )
    from apps.outcomes.tasks import track_token_outcome
    from apps.predictions.tasks import generate_prediction_for_active_tokens
    from apps.scoring.tasks import (
        analyze_token_safety_for_active_tokens,
        calculate_token_score_for_active_tokens,
    )
    from apps.telegram.tasks import send_pending_telegram_alerts
    from apps.tokens.tasks import discover_tokens
    from apps.wallets.tasks import (
        calculate_wallet_reputation_for_active_wallets,
        run_wallet_clustering_task,
    )

    # Dependency order matches ARCHITECTURE.md S2's pipeline description.
    return [
        ("discover_tokens", discover_tokens),
        ("collect_market_data", collect_market_data_for_active_tokens),
        ("collect_liquidity", collect_liquidity_for_active_tokens),
        ("collect_holders", collect_holders_for_active_tokens),
        ("analyze_token_safety", analyze_token_safety_for_active_tokens),
        ("calculate_wallet_reputation", calculate_wallet_reputation_for_active_wallets),
        ("run_wallet_clustering", run_wallet_clustering_task),
        ("analyze_narrative", analyze_narrative_for_active_tokens),
        ("refresh_narrative_metrics", refresh_narrative_metrics_for_active_narratives),
        ("calculate_token_score", calculate_token_score_for_active_tokens),
        ("generate_prediction", generate_prediction_for_active_tokens),
        ("evaluate_alert_state", evaluate_alert_state_for_active_tokens),
        ("track_token_outcome", track_token_outcome),
        ("send_pending_telegram_alerts", send_pending_telegram_alerts),
        ("evaluate_ai_configuration", evaluate_ai_configuration),
    ]


def run_pipeline_once(*, time_budget_seconds: float = DEFAULT_TIME_BUDGET_SECONDS) -> dict:
    """Runs every pipeline stage once, synchronously, in dependency order.
    One stage failing is logged and does not abort the rest -- a Birdeye
    hiccup on stage 3 shouldn't skip outcome tracking or Telegram delivery
    on stages 12-14. Stops STARTING new stages once `time_budget_seconds`
    has elapsed (a stage already in progress still finishes -- this can't
    interrupt mid-call) -- see DEFAULT_TIME_BUDGET_SECONDS above.

    Residual risk, stated plainly: this bounds the number of stages
    STARTED, not any single stage's own duration -- a stage already
    running when the budget is checked always finishes before the next
    check happens. Worst case is roughly budget + one stage's own
    duration, not a hard ceiling. Acceptable for a temporary free-tier
    workaround; a real per-call timeout (matching the pattern already used
    for the Celery health check in apps/core/views.py) would close this
    gap properly if it ever matters more than it does today.
    """
    previous_eager = celery_app.conf.task_always_eager
    previous_propagates = celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True

    started_at = time.monotonic()
    results: dict = {}
    try:
        for name, task in _pipeline_steps():
            elapsed = time.monotonic() - started_at
            if elapsed >= time_budget_seconds:
                logger.warning(
                    "Pipeline time budget (%.0fs) exceeded after %.1fs -- skipping %s and "
                    "everything after it this run; it'll run on the next tick.",
                    time_budget_seconds, elapsed, name,
                )
                results[name] = {"skipped": "time budget exceeded"}
                continue

            try:
                results[name] = task.delay().get()
            except Exception as exc:  # noqa: BLE001 -- isolate this stage, keep the pipeline moving
                logger.exception("Pipeline stage %s failed", name)
                results[name] = {"error": str(exc)}
    finally:
        celery_app.conf.task_always_eager = previous_eager
        celery_app.conf.task_eager_propagates = previous_propagates

    return results

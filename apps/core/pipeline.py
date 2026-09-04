"""Synchronous, worker-free pipeline runner for deployments with no Celery
worker/beat (a genuinely-free hosting path: web service + Postgres only,
see ARCHITECTURE.md's deployment notes). An external free scheduler
(cron-job.org, every 2 minutes -- GitHub Actions' effective ~15 min
reliability floor was too coarse, see .github/workflows/run-pipeline.yml)
calls the /api/v1/pipeline/run/ endpoint on an interval, which runs this
-- one full pass through every stage of the pipeline, in the same
dependency order CELERY_BEAT_SCHEDULE would otherwise run them
independently on their own intervals.

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
timeout on any host -- confirmed live: gunicorn's default 30s worker
timeout killed a real production request mid-stage, returning a bare 500.
STAGE_TIMEOUT_SECONDS below closes that gap with a real hard timeout (not
just a "stop starting new stages" soft check), and render.yaml's
`--timeout 90` gives gunicorn itself enough headroom to never be the one
that kills the request first.

One mitigating property worth knowing: a timed-out stage's thread isn't
killed, only abandoned (see _run_stage_with_timeout) -- it keeps running
in the background, in the same worker process, for as long as that
process stays alive, and its writes still land in the database. So real
progress on a "timed out" stage often continues to happen for a while
after the HTTP response has already returned, not just during the bounded
window this function itself waits for.

The honest consequence of all this bounding: a full cycle through all 14
stages still takes several cron ticks to complete once -- roughly the
0-25s budget worth of stages per 2-minute tick, so realistically 30-60
minutes at real token counts (down from hours at the previous 15-minute
GitHub Actions cadence, but not re-measured empirically at 2 minutes --
treat as an estimate). This is a genuinely slow,
eventually-consistent substitute for the real pipeline, not a real-time
one -- fine for occasional/manual runs or a token count in the single
digits, not a real substitute for Redis + a worker if anything resembling
the PRD's intended near-real-time behavior matters. Every stage now also
runs at the SAME cadence (this endpoint's calling interval), not each at
its own tuned interval the way CELERY_BEAT_SCHEDULE has them. Revisit
(delete this file and the /api/v1/pipeline/run/ endpoint) once a real
worker gets added -- see ARCHITECTURE.md S5.1.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError

from config.celery import app as celery_app

logger = logging.getLogger("alpha.pipeline")

# Real external API calls (Birdeye/QuickNode, per active token, across
# several stages) turned out live-testing to be much slower than mock-data
# tests suggested. Two bounds work together:
#   - STAGE_TIMEOUT_SECONDS: a HARD per-stage ceiling (via a worker thread
#     + Future.result(timeout=...), the same pattern apps/core/views.py's
#     Celery health check already uses to bound an otherwise-uninterruptible
#     blocking call). If a stage doesn't finish in time, this function
#     stops WAITING on it and moves on -- the abandoned thread keeps
#     running in the background (harmless: it's just DB writes/API calls
#     that would happen anyway, same as a real Celery worker processing it
#     asynchronously) rather than blocking the whole pipeline run on one
#     slow stage.
#   - TIME_BUDGET_SECONDS: stops STARTING new stages once total elapsed
#     time crosses this, so a run that hits several slow-but-not-timed-out
#     stages in a row still returns promptly.
# Together, worst case for one call to run_pipeline_once() is roughly
# TIME_BUDGET_SECONDS + STAGE_TIMEOUT_SECONDS -- comfortably under
# gunicorn's --timeout 90 (render.yaml), which is itself only a backstop
# that should rarely matter now.
DEFAULT_STAGE_TIMEOUT_SECONDS = 25
DEFAULT_TIME_BUDGET_SECONDS = 25


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

    # Dependency order matches ARCHITECTURE.md S2's pipeline description,
    # with one deliberate exception: discover_tokens runs LAST, not first.
    # Confirmed live: it's often the slowest single call (real Birdeye
    # latency); with it first, no other stage got a turn. Finding new
    # tokens is inherently less time-sensitive than keeping known ones
    # current, so it goes last and is the stage most likely to get skipped
    # when time runs out. Also confirmed live, though: this isn't unique
    # to discover_tokens -- ANY stage making real per-token API calls
    # (collect_market_data/liquidity/holders) can similarly exceed the
    # budget once there are 20-30+ active tokens each needing a real
    # round trip. Reordering only changes WHICH single stage tends to be
    # the one that times out on a given run, not whether one will.
    return [
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
        ("discover_tokens", discover_tokens),
    ]


def _get_eagerly(task):
    """`task.delay().get()`, permitted via Celery's own sanctioned escape
    hatch (allow_join_result()). Celery normally forbids calling .get() on
    a result from inside task execution -- a real deadlock risk with a
    real worker pool (a worker blocking on a subtask queued behind it on
    the same worker). That risk doesn't exist here (task_always_eager mode
    runs everything synchronously in-process, there's no separate worker
    to deadlock with), but the guard itself is a process-global flag, not
    thread-local -- running `.delay()` from inside a ThreadPoolExecutor
    thread (see _run_stage_with_timeout) trips it regardless, confirmed
    live. allow_join_result() is Celery's own documented way to lift it
    for a scope known to be safe.
    """
    from celery.result import allow_join_result

    with allow_join_result():
        return task.delay().get()


def _run_stage_with_timeout(task, *, timeout_seconds: float):
    """Runs `task.delay().get()` with a hard wall-clock ceiling. Not using
    a context manager for the executor: __exit__ would call
    shutdown(wait=True), blocking until the (possibly still-running,
    abandoned) thread finishes -- exactly the hang this exists to avoid.
    shutdown(wait=False) detaches it instead; Django gives that thread its
    own DB connection, so it finishes safely on its own even though
    nothing is waiting on it anymore.
    """
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        return executor.submit(_get_eagerly, task).result(timeout=timeout_seconds)
    finally:
        executor.shutdown(wait=False)


def run_pipeline_once(
    *,
    time_budget_seconds: float = DEFAULT_TIME_BUDGET_SECONDS,
    stage_timeout_seconds: float = DEFAULT_STAGE_TIMEOUT_SECONDS,
) -> dict:
    """Runs every pipeline stage once, synchronously, in dependency order.
    One stage failing (or timing out) is logged and does not abort the
    rest -- a Birdeye hiccup on stage 3 shouldn't skip outcome tracking or
    Telegram delivery on stages 12-14. See the module docstring for how
    `time_budget_seconds` and `stage_timeout_seconds` bound total runtime
    together.
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
                results[name] = _run_stage_with_timeout(task, timeout_seconds=stage_timeout_seconds)
            except FutureTimeoutError:
                logger.warning(
                    "Pipeline stage %s did not finish within %.0fs -- moving on; it keeps "
                    "running in the background and its work will still be saved.",
                    name, stage_timeout_seconds,
                )
                results[name] = {"timed_out": True}
            except Exception as exc:  # noqa: BLE001 -- isolate this stage, keep the pipeline moving
                logger.exception("Pipeline stage %s failed", name)
                results[name] = {"error": str(exc)}
    finally:
        celery_app.conf.task_always_eager = previous_eager
        celery_app.conf.task_eager_propagates = previous_propagates

    return results

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
timeout on any host -- confirmed live twice, from two different directions:
gunicorn's default 30s worker timeout once killed a real production
request mid-stage (returning a bare 500), and separately, cron-job.org's
own fixed 30s request timeout marks a run as failed if this endpoint
doesn't respond in time (their side, not ours -- Django/gunicorn keep
working regardless, see the mitigating property below). gunicorn's side is
covered by render.yaml's `--timeout 90`. cron-job.org's 30s cannot be
raised on their free plan, so it's now the tighter, binding constraint:
STAGE_TIMEOUT_SECONDS and TIME_BUDGET_SECONDS below are sized to keep a
normal response comfortably under it, not under gunicorn's more generous
90s.

One mitigating property worth knowing: a timed-out stage's thread isn't
killed, only abandoned (see _run_stage_with_timeout) -- it keeps running
in the background, in the same worker process, for as long as that
process stays alive, and its writes still land in the database. So real
progress on a "timed out" stage often continues to happen for a while
after the HTTP response has already returned, not just during the bounded
window this function itself waits for.

The honest consequence of all this bounding: a full cycle through all 14
stages still takes several cron ticks to complete once via run_pipeline_once()
alone. With TIME_BUDGET_SECONDS shrunk to fit under cron-job.org's 30s cap,
most ticks now only get through one real-API-heavy stage before the budget
trips -- see pipeline_loop() below for how this is actually avoided in
production now. This is a genuinely slow, eventually-consistent substitute
for the real pipeline on its own -- fine for occasional/manual runs or a
token count in the single digits, not a real substitute for Redis + a
worker if anything resembling the PRD's intended near-real-time behavior
matters through run_pipeline_once() alone.

pipeline_loop(), below, is the actual production mechanism now: a single
background thread, started once per gunicorn worker process (see
gunicorn.conf.py's post_worker_init hook, gated behind the
PIPELINE_INPROCESS_LOOP env var), that loops through every stage
continuously for as long as the process stays alive -- no external
HTTP-timeout constraint at all, since nothing is waiting on an HTTP
response for it. This is what actually gets this deployment path close to
near-real-time: cron-job.org's job is demoted from "trigger every stage"
to "keep the free web service from spinning down" (Render spins down a
free web service after 15 minutes with no *inbound* HTTP traffic --
confirmed against their docs -- which a purely-internal background thread
does nothing to prevent), calling the cheap, unauthenticated
/api/v1/health/ endpoint every ~10 minutes instead of
/api/v1/pipeline/run/ every 2. run_pipeline_once() and
/api/v1/pipeline/run/ still exist for manual/on-demand triggering and
tests, but are no longer load-bearing for the main automation. Revisit
(delete this file, gunicorn.conf.py's hook, and the /api/v1/pipeline/run/
endpoint) once a real Celery worker + beat + Redis get added -- see
ARCHITECTURE.md S5.1.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError

from django.core.cache import cache

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
# TIME_BUDGET_SECONDS + STAGE_TIMEOUT_SECONDS. The binding constraint on
# these two values is no longer gunicorn's --timeout 90 (render.yaml) --
# it's cron-job.org's own fixed 30s request timeout (confirmed live: a run
# that exceeded 30s came back as a failed/timed-out job on their end, even
# though gunicorn and Django were still happily working on it). cron-job.org
# does not allow that 30s to be raised on the free plan, so the values below
# target a worst case with real margin under it instead. Known trade-off:
# a smaller budget also means fewer stages get a turn per invocation
# (often just one, if it's a real-API-heavy stage) -- see the "honest
# consequence" paragraph above for what that does to full-cycle timing.
DEFAULT_STAGE_TIMEOUT_SECONDS = 18
DEFAULT_TIME_BUDGET_SECONDS = 8


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

    Each call to _run_stage_with_timeout spins up a brand-new thread, and
    Django hands each thread its own DB connection lazily on first use.
    Under run_pipeline_once() (one HTTP request every so often) that's a
    handful of short-lived connections -- not worth worrying about. Under
    pipeline_loop() (running continuously, indefinitely) it would leak one
    connection per stage per cycle over hours/days, risking Postgres's
    free-tier connection ceiling. connections.close_all() is thread-local
    (django.db.ConnectionHandler stores connections in threading.local()),
    so this only ever closes the connection this specific stage-thread
    opened -- the pipeline_loop() thread itself never opens one directly
    (it only ever calls into this function via a fresh stage-thread), so
    there's nothing of its own left dangling either.
    """
    from celery.result import allow_join_result
    from django.db import connections

    try:
        with allow_join_result():
            return task.delay().get()
    finally:
        connections.close_all()


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


# --- pipeline_loop(): the in-process background loop, see module docstring ---

# No external HTTP caller is ever waiting on a stage run inside the loop, so
# this can be far more generous than run_pipeline_once()'s cron-job.org-
# bound DEFAULT_STAGE_TIMEOUT_SECONDS -- sized to comfortably outlast a real
# slow stage (622s/14 real stages ~= 44s average, so 90s gives real margin)
# rather than to fit under an external request timeout.
LOOP_STAGE_TIMEOUT_SECONDS = 90
# Brief pause between full cycles -- only matters when a cycle finishes
# very fast (e.g. zero active tokens, all mock/local dev), so an otherwise
# empty loop doesn't spin the CPU doing nothing thousands of times a second.
LOOP_CYCLE_SLEEP_SECONDS = 3
PIPELINE_LOOP_HEARTBEAT_CACHE_KEY = "pipeline_loop:heartbeat"


def _record_loop_heartbeat(stage_name: str, outcome: str) -> None:
    """Lets apps/core/views.py's health check report that the loop is
    actually alive and how far it's gotten, without needing a second
    process or a DB migration -- Django's cache framework is enough since
    the loop thread and the request thread reading it back share the same
    process (pipeline_loop() only ever runs safely with a single gunicorn
    worker -- see gunicorn.conf.py / render.yaml's --workers 1)."""
    cache.set(
        PIPELINE_LOOP_HEARTBEAT_CACHE_KEY,
        {"stage": stage_name, "outcome": outcome, "at": time.time()},
        timeout=None,
    )


def _run_one_loop_cycle() -> None:
    """One full pass over every stage, each bounded by
    LOOP_STAGE_TIMEOUT_SECONDS and isolated from the others the same way
    run_pipeline_once() isolates them -- one stage failing or timing out
    doesn't stop the rest from getting a turn. Split out from
    pipeline_loop() itself purely so tests can call one cycle directly
    instead of having to break out of an infinite loop.
    """
    for name, task in _pipeline_steps():
        try:
            _run_stage_with_timeout(task, timeout_seconds=LOOP_STAGE_TIMEOUT_SECONDS)
        except FutureTimeoutError:
            logger.warning(
                "Pipeline loop: stage %s did not finish within %.0fs -- moving on; it "
                "keeps running in the background and its work will still be saved.",
                name, LOOP_STAGE_TIMEOUT_SECONDS,
            )
            _record_loop_heartbeat(name, "timed_out")
        except Exception:  # noqa: BLE001 -- isolate this stage, keep the loop going
            logger.exception("Pipeline loop: stage %s failed", name)
            _record_loop_heartbeat(name, "error")
        else:
            _record_loop_heartbeat(name, "ok")


def pipeline_loop() -> None:
    """Entry point for the background thread gunicorn.conf.py's
    post_worker_init hook starts. Runs forever (for the life of the worker
    process) once started -- see the module docstring for why this exists
    and what it replaces.

    Safe ONLY with exactly one gunicorn worker process (render.yaml's
    startCommand pins --workers 1 for this reason). A Postgres advisory
    lock was tried here as a defense-in-depth safety net against an
    accidental multi-worker config, but was proven live, against this
    project's actual database, to NOT provide real mutual exclusion:
    Neon's pooled connection string (the "-pooler" hostname in
    DATABASE_URL) runs PgBouncer in transaction-pooling mode, which can
    silently hand two different clients' statements to the same
    underlying Postgres backend session (or reassign a client to a
    different one between statements) -- session-scoped locks like
    pg_try_advisory_lock/pg_advisory_unlock don't reliably survive that.
    A working fix would need Neon's separate *unpooled* connection string
    held open for the lock specifically, which isn't configured here --
    not worth the added config surface for what's meant to be a secondary
    safety net, when the primary one (--workers 1) is sufficient on its
    own. Do not resurrect the advisory-lock approach against a pooled
    connection string without re-verifying it live first.

    Deliberately does not restore task_always_eager/task_eager_propagates
    the way run_pipeline_once() does: this deployment path has no real
    broker to begin with (that's the whole reason this file exists), and
    nothing else in this process calls .delay() outside of this loop and
    run_pipeline_once() (both of which need eager mode anyway), so there's
    nothing for a restore to protect here, and the loop never returns in
    normal operation regardless.
    """
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True

    logger.info("Pipeline loop: starting continuous in-process run.")
    while True:
        _run_one_loop_cycle()
        time.sleep(LOOP_CYCLE_SLEEP_SECONDS)

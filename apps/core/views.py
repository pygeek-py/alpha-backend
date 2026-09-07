import time

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.utils import OperationalError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.pipeline import PIPELINE_LOOP_HEARTBEAT_CACHE_KEY, run_pipeline_once
from apps.core.services import get_overview_stats

# Generous relative to LOOP_STAGE_TIMEOUT_SECONDS (90s, apps/core/pipeline.py)
# -- a single genuinely slow real-API stage taking its full timeout shouldn't
# by itself make this report "stale"; only a loop that's actually stopped
# advancing should.
PIPELINE_LOOP_STALE_AFTER_SECONDS = 300


def _check_database() -> dict:
    started = time.monotonic()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return {"status": "ok", "latency_ms": round((time.monotonic() - started) * 1000, 1)}
    except OperationalError as exc:
        return {"status": "error", "detail": str(exc)}


def _check_redis() -> dict:
    started = time.monotonic()
    try:
        marker = "health:ping"
        cache.set(marker, "pong", timeout=5)
        ok = cache.get(marker) == "pong"
        return {
            "status": "ok" if ok else "error",
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
        }
    except Exception as exc:  # noqa: BLE001 - any cache backend failure is a health issue
        return {"status": "error", "detail": str(exc)}


def _check_celery() -> dict:
    """celery.control.ping()'s own `timeout` only bounds how long it waits for
    worker *replies* -- if the broker host itself has no listener, the initial
    connection attempt underneath can still block for the OS's TCP retry
    window. Running it in a worker thread with a hard result() timeout
    guarantees this check (and therefore the whole health endpoint) always
    returns promptly regardless of what the broker connection is doing.
    """
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FutureTimeoutError

    from config.celery import app as celery_app

    def ping():
        return celery_app.control.ping(timeout=1.0)

    started = time.monotonic()
    # Not using ThreadPoolExecutor as a context manager: __exit__ would call
    # shutdown(wait=True), which blocks until the ping thread actually
    # finishes -- exactly the hang we're trying to avoid. shutdown(wait=False)
    # detaches it instead; the thread is cleaned up whenever the underlying
    # blocking socket call eventually returns, without holding up this request.
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        replies = executor.submit(ping).result(timeout=3.0)
    except FutureTimeoutError:
        executor.shutdown(wait=False)
        return {"status": "unavailable", "detail": "broker unreachable (timed out)"}
    except Exception as exc:  # noqa: BLE001 - broker down, worker unreachable, etc.
        executor.shutdown(wait=False)
        return {"status": "unavailable", "detail": str(exc)}
    executor.shutdown(wait=False)

    latency_ms = round((time.monotonic() - started) * 1000, 1)
    if replies:
        return {"status": "ok", "workers": len(replies), "latency_ms": latency_ms}
    return {"status": "unavailable", "workers": 0, "detail": "no workers responded"}


def _check_pipeline_loop() -> dict:
    """Surfaces apps/core/pipeline.py's pipeline_loop() heartbeat -- the
    only way to see from the outside whether the free-tier in-process loop
    is actually alive and making progress, since it has no separate
    process of its own to inspect."""
    if not settings.PIPELINE_INPROCESS_LOOP_ENABLED:
        return {"status": "disabled"}

    heartbeat = cache.get(PIPELINE_LOOP_HEARTBEAT_CACHE_KEY)
    if heartbeat is None:
        return {"status": "not_started"}

    age_seconds = time.time() - heartbeat["at"]
    return {
        "status": "ok" if age_seconds < PIPELINE_LOOP_STALE_AFTER_SECONDS else "stale",
        "last_stage": heartbeat["stage"],
        "last_outcome": heartbeat["outcome"],
        "age_seconds": round(age_seconds, 1),
    }


class HealthCheckView(APIView):
    """Reports DB, Redis (cache/broker), Celery worker, and pipeline-loop
    liveness. This is also cron-job.org's keep-alive ping target now (see
    apps/core/pipeline.py's module docstring) -- AllowAny and cheap on
    purpose, since its only job now is to generate the inbound traffic
    Render's free-tier spin-down looks for, every ~10 minutes.

    Celery/pipeline-loop being "unavailable"/"disabled" does not make the
    endpoint report failure overall -- neither is required for the API
    itself to work -- but database or cache failures do, since the API
    cannot function without them.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        checks = {
            "database": _check_database(),
            "redis": _check_redis(),
            "celery": _check_celery(),
            "pipeline_loop": _check_pipeline_loop(),
        }
        critical_ok = all(checks[name]["status"] == "ok" for name in ("database", "redis"))
        overall = "ok" if critical_ok else "degraded"
        status_code = 200 if critical_ok else 503
        return Response({"status": overall, "checks": checks}, status=status_code)


class OverviewStatsView(APIView):
    """PRD S39 Overview dashboard stats. Uses the default IsAuthenticated
    permission (unlike the health check) -- this is operator dashboard data,
    not a public liveness probe."""

    def get(self, request):
        return Response(get_overview_stats())


class RunPipelineView(APIView):
    """For deployments with no Celery worker/beat: an external free
    scheduler (GitHub Actions cron, see .github/workflows/run-pipeline.yml)
    calls this on an interval to run one full pipeline pass synchronously,
    in-process -- see apps/core/pipeline.py. Real, resource-costing work
    (external API calls, a real Telegram send if anything's pending) --
    IsAuthenticated (default) plus a tight throttle_scope, never a public
    endpoint."""

    throttle_scope = "run_pipeline"

    def post(self, request):
        return Response(run_pipeline_once())

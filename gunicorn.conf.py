"""Gunicorn server config -- auto-loaded from the current working directory
(https://docs.gunicorn.org/en/stable/settings.html), so `gunicorn
config.wsgi:application --timeout 90` (render.yaml's startCommand) picks
this up with no command-line change needed. Only ever read by that
process: `manage.py` commands (migrate, tests, shell) and the separate
Celery worker/beat processes never invoke gunicorn, so nothing here can
affect them.
"""
import threading


def post_worker_init(worker):
    """Fires exactly once per worker process, right after the WSGI app
    (config.wsgi:application) has finished loading -- which means Django
    is already set up (django.setup() runs as part of importing
    config.wsgi), so it's safe to touch models/the DB from here.

    Gated behind PIPELINE_INPROCESS_LOOP so this stays a no-op everywhere
    except the actual live free-tier deployment: local dev, tests, and any
    future deployment that adds a real Celery worker + beat + Redis (see
    ARCHITECTURE.md S5.1) should never run this loop, since a real beat
    already does this job properly and running both would double up on
    every stage.

    Only ever safe with exactly one worker process -- render.yaml's
    startCommand pins `--workers 1` for this reason, and that pin is load-
    bearing, not cosmetic: a Postgres advisory lock was tried as a second,
    defense-in-depth safety net against an accidental multi-worker config,
    but was proven live (against this project's actual Neon-pooled
    DATABASE_URL) to not provide real mutual exclusion -- see
    apps/core/pipeline.py's pipeline_loop() docstring for the full story.
    --workers 1 is the only thing preventing two copies of this loop from
    running concurrently against the same real Birdeye/QuickNode rate
    limits; do not remove it without replacing this hook's protection some
    other way first.
    """
    from django.conf import settings

    if not settings.PIPELINE_INPROCESS_LOOP_ENABLED:
        return

    from apps.core.pipeline import pipeline_loop

    threading.Thread(target=pipeline_loop, name="pipeline-loop", daemon=True).start()

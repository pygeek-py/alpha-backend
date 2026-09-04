from .base import *  # noqa: F401,F403

DEBUG = False

# The test suite must run without any external services (Postgres, Redis) --
# it should be runnable in CI or offline, not just when docker-compose is up.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        # SQLite only allows one writer at a time; the default 5s busy
        # timeout isn't quite enough for apps/core/pipeline.py's tests,
        # which genuinely run real DB writes from a background thread
        # (real per-stage timeout enforcement, not a test artifact --
        # production uses Postgres, which handles concurrent connections
        # normally). Raised so a transient lock wait retries instead of
        # immediately raising "database is locked".
        "OPTIONS": {"timeout": 20},
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Same "must run without external services" principle applies to data
# providers, not just Postgres/Redis -- base.py reads these from whatever
# real .env happens to be sitting in the working directory (e.g. real
# Birdeye/QuickNode values set for a deployment), and without this override
# the test suite would silently start making real, rate-limited external
# API calls and failing on things like a factory-generated fake token
# address never being a real Birdeye-known token.
SOLANA_CHAIN_DATA_PROVIDER = "mock"
SOLANA_MARKET_DATA_PROVIDER = "mock"
SOLANA_WALLET_DATA_PROVIDER = "mock"
SOCIAL_DATA_PROVIDER = "none"

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

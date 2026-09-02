"""Settings shared by every environment. Environment-specific files
(dev.py / prod.py / test.py) import * from here and override as needed."""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)

SECRET_KEY = env("DJANGO_SECRET_KEY", default="insecure-dev-key-change-me")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third-party
    "rest_framework",
    # REST_FRAMEWORK's DEFAULT_AUTHENTICATION_CLASSES below already lists
    # TokenAuthentication -- this app provides the Token model/table it
    # needs. Not previously registered, which would have broken the first
    # time anything actually tried to authenticate with a token (this
    # batch's /telegram/test/ is the first real authenticated endpoint).
    "rest_framework.authtoken",
    "django_filters",
    "corsheaders",
    # domain apps
    "apps.core",
    "apps.users",
    "apps.tokens",
    "apps.market_data",
    "apps.liquidity",
    "apps.holders",
    "apps.wallets",
    "apps.narratives",
    "apps.scoring",
    "apps.predictions",
    "apps.alerts",
    "apps.outcomes",
    "apps.ml",
    "apps.configuration",
    "apps.telegram",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.RequestLoggingMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

AUTH_USER_MODEL = "users.User"

DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://alpha:alpha@localhost:5432/alpha"),
}
# A health check (or any request) must never hang indefinitely if the database
# is unreachable -- an unreachable host with no listener can otherwise block
# for the OS's full TCP retry window instead of failing fast.
DATABASES["default"].setdefault("OPTIONS", {})["connect_timeout"] = 3

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Redis (cache + Celery broker/backend) ---------------------------------

REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            # Same reasoning as DATABASES connect_timeout above -- fail fast, don't hang.
            # These are passed straight through to redis.ConnectionPool.from_url(),
            # not nested under a pool-kwargs key.
            "socket_connect_timeout": 3,
            "socket_timeout": 3,
        },
    }
}

# --- Celery ------------------------------------------------------------------

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_DEFAULT_QUEUE = "ingestion"
CELERY_TASK_ROUTES = {
    # Every task in this project registers under a short "<app_label>.<name>"
    # name (via @shared_task(name=...)), never its dotted Python module path --
    # these patterns must match that, not "apps.<app>.tasks.*" (which never
    # matches any real task and silently sent every task to the default queue).
    "tokens.*": {"queue": "ingestion"},
    "market_data.*": {"queue": "ingestion"},
    "liquidity.*": {"queue": "ingestion"},
    "holders.*": {"queue": "ingestion"},
    "wallets.*": {"queue": "analysis"},
    "narratives.*": {"queue": "analysis"},
    "scoring.*": {"queue": "analysis"},
    "predictions.*": {"queue": "analysis"},
    "alerts.*": {"queue": "alerts"},
    "telegram.*": {"queue": "alerts"},
    "outcomes.*": {"queue": "analysis"},
    "ml.*": {"queue": "ml"},
    "configuration.*": {"queue": "ml"},
}

# Periodic ingestion sweeps. Intervals are placeholders sized for demoing
# against the mock provider -- age-aware polling frequency (PRD S15: a 5-
# minute-old token polled far more often than a 3-hour-old one) is a Batch 5
# refinement, not implemented here. Requires `celery -A config beat` running
# alongside the worker; without it these tasks only run when triggered manually.
CELERY_BEAT_SCHEDULE = {
    "discover-tokens": {
        "task": "tokens.discover_tokens",
        "schedule": 300.0,
    },
    "collect-market-data": {
        "task": "market_data.collect_market_data_for_active_tokens",
        "schedule": 120.0,
    },
    "collect-liquidity": {
        "task": "liquidity.collect_liquidity_for_active_tokens",
        "schedule": 120.0,
    },
    "collect-holders": {
        "task": "holders.collect_holders_for_active_tokens",
        "schedule": 180.0,
    },
    "analyze-token-safety": {
        "task": "scoring.analyze_token_safety_for_active_tokens",
        "schedule": 180.0,
    },
    "calculate-wallet-reputation": {
        "task": "wallets.calculate_wallet_reputation_for_active_wallets",
        "schedule": 300.0,
    },
    "run-wallet-clustering": {
        "task": "wallets.run_wallet_clustering",
        "schedule": 600.0,
    },
    "analyze-narrative": {
        "task": "narratives.analyze_narrative_for_active_tokens",
        "schedule": 240.0,
    },
    "refresh-narrative-metrics": {
        "task": "narratives.refresh_narrative_metrics_for_active_narratives",
        "schedule": 300.0,
    },
    "calculate-token-score": {
        "task": "scoring.calculate_token_score_for_active_tokens",
        "schedule": 300.0,
    },
    "generate-prediction": {
        "task": "predictions.generate_prediction_for_active_tokens",
        "schedule": 300.0,
    },
    "evaluate-ai-configuration": {
        "task": "configuration.evaluate_ai_configuration",
        "schedule": 900.0,
    },
    "evaluate-alert-state": {
        "task": "alerts.evaluate_alert_state_for_active_tokens",
        "schedule": 120.0,
    },
    "track-token-outcome": {
        "task": "outcomes.track_token_outcome",
        "schedule": 60.0,
    },
    "send-pending-telegram-alerts": {
        "task": "telegram.send_pending_telegram_alerts",
        "schedule": 30.0,
    },
}

# --- Django REST Framework ----------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.CursorPagination",
    "PAGE_SIZE": 50,
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
}

# --- CORS (frontend dev server) ------------------------------------------------

CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS", default=["http://localhost:3000", "http://127.0.0.1:3000"]
)

# --- Data provider selection (see providers/registry.py) ----------------------

SOLANA_CHAIN_DATA_PROVIDER = env("SOLANA_CHAIN_DATA_PROVIDER", default="mock")
SOLANA_MARKET_DATA_PROVIDER = env("SOLANA_MARKET_DATA_PROVIDER", default="mock")
SOLANA_WALLET_DATA_PROVIDER = env("SOLANA_WALLET_DATA_PROVIDER", default="mock")
# Default "none" (not "mock") -- narrative strength/momentum get persisted
# and consumed by downstream scoring; silently blending in simulated social
# data by default would contaminate an otherwise on-chain-only pipeline.
# Set to "mock" explicitly to exercise the blending path in local dev/tests.
SOCIAL_DATA_PROVIDER = env("SOCIAL_DATA_PROVIDER", default="none")

BIRDEYE_API_KEY = env("BIRDEYE_API_KEY", default="")
HELIUS_API_KEY = env("HELIUS_API_KEY", default="")
# The Solana RPC HTTP Provider URL from the QuickNode dashboard -- not the
# QN_... account-level API key, which is a different credential used for
# QuickNode's REST/Marketplace products, not raw JSON-RPC calls.
QUICKNODE_RPC_URL = env("QUICKNODE_RPC_URL", default="")
TWITTER_BEARER_TOKEN = env("TWITTER_BEARER_TOKEN", default="")

TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN", default="")

# --- Logging --------------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(asctime)s %(levelname)s %(name)s: %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": env("DJANGO_LOG_LEVEL", default="INFO"),
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "celery": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "alpha": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
    },
}

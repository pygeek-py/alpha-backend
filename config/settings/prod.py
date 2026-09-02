from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import SECRET_KEY  # noqa: F401

DEBUG = False

# base.py's SECRET_KEY default exists only so `manage.py` commands work
# without a .env file in local dev -- it must never reach production. Fail
# loudly at startup rather than silently signing sessions/tokens with a
# publicly-known key.
if SECRET_KEY == "insecure-dev-key-change-me":
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY is not set (or still the insecure default) -- "
        "set a real, unique secret key before running with prod settings."
    )

SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)  # noqa: F405
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 7
SECURE_HSTS_INCLUDE_SUBDOMAINS = True

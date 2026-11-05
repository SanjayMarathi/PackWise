"""Settings for the automated test suite (pytest). Uses PostgreSQL like production."""

from .base import *  # noqa: F403
from .base import LOGGING, REST_FRAMEWORK, database_config

DEBUG = False
SECRET_KEY = "test-only-secret-key-not-used-anywhere-else-0123456789abcdef"  # noqa: S105 - test-only value
ALLOWED_HOSTS = ["testserver", "localhost"]

DATABASES = {
    "default": database_config("postgres://packwise:packwise@localhost:5432/packwise"),
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Serve static files from app directories (as in development) instead of requiring collectstatic.
WHITENOISE_AUTOREFRESH = True
WHITENOISE_USE_FINDERS = True

# Keep throttling active (so its wiring is exercised) but out of the way of normal tests.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {"anon": "100000/minute", "recommend": "100000/minute"},
}

LOGGING["loggers"]["packwise"]["level"] = "WARNING"

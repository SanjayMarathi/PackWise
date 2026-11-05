"""Settings shared by every environment.

Environment-specific modules (development, production, test) import from here
and override what differs. Everything secret or deployment-specific comes from
environment variables. See ``.env.example``.
"""

from __future__ import annotations

import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------- env helpers


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def env_required(name: str) -> str:
    value = env(name)
    if value is None:
        raise ImproperlyConfigured(f"The {name} environment variable is required.")
    return value


def env_bool(name: str, default: bool = False) -> bool:
    value = env(name)
    if value is None:
        return default
    if value.lower() in {"1", "true", "yes", "on"}:
        return True
    if value.lower() in {"0", "false", "no", "off"}:
        return False
    raise ImproperlyConfigured(f"{name} must be a boolean, got {value!r}.")


def env_int(name: str, default: int) -> int:
    value = env(name)
    try:
        return default if value is None else int(value)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an integer, got {value!r}.") from exc


def env_list(name: str, default: str = "") -> list[str]:
    return [part.strip() for part in (env(name, default) or "").split(",") if part.strip()]


def database_config(default_url: str | None = None) -> dict:
    url = env("DATABASE_URL", default_url)
    if url is None:
        raise ImproperlyConfigured("The DATABASE_URL environment variable is required.")
    return dj_database_url.parse(
        url,
        conn_max_age=env_int("DB_CONN_MAX_AGE", 60),
        conn_health_checks=True,
    )


# ---------------------------------------------------------------- core

DEBUG = False
SECRET_KEY = env("DJANGO_SECRET_KEY")  # each environment decides whether it is required
ALLOWED_HOSTS: list[str] = env_list("DJANGO_ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "inventory",
    "orders",
    "packing",
    "assistant",
    "web",
]

MIDDLEWARE = [
    "common.middleware.HealthCheckMiddleware",  # first: probes bypass host checks (see its docstring)
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES: dict = {}  # set per environment via database_config()
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

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

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Reject absurdly large request bodies before they reach a serializer.
DATA_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024  # 1 MiB


# ---------------------------------------------------------------- REST framework

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    # The API is intentionally unauthenticated (see README, "Known limitations").
    # Without authentication classes there is no session-based CSRF surface.
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_PAGINATION_CLASS": "common.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "common.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("THROTTLE_ANON_RATE", "120/minute"),
        "recommend": env("THROTTLE_RECOMMEND_RATE", "30/minute"),
        "assistant": env("THROTTLE_ASSISTANT_RATE", "10/minute"),
    },
    # Render decimals as JSON numbers, e.g. "cost": 35.0 rather than "35.00".
    "COERCE_DECIMAL_TO_STRING": False,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "PackWise API",
    "DESCRIPTION": (
        "Intelligent 3D packaging and shipping-box recommendation. "
        "Units: dimensions in centimetres (cm), weight in kilograms (kg), cost in INR."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": r"/api/",
}


# ---------------------------------------------------------------- PackWise domain settings

PACKWISE = {
    # Default box-ranking strategy: lowest_cost | best_utilization | smallest_box
    "RANKING_STRATEGY": env("PACKWISE_RANKING_STRATEGY", "lowest_cost"),
    # Upper bound on physical units per order. It caps the packing engine's work per request.
    "MAX_ITEMS_PER_ORDER": env_int("PACKWISE_MAX_ITEMS_PER_ORDER", 200),
    # Maximum distinct order lines per order.
    "MAX_LINES_PER_ORDER": env_int("PACKWISE_MAX_LINES_PER_ORDER", 50),
    # 0 disables the gravity-support check (void fill is assumed); 1 = full support.
    "MIN_SUPPORT_RATIO": float(env("PACKWISE_MIN_SUPPORT_RATIO", "0") or 0),
}
APP_VERSION = env("APP_VERSION", "1.0.0")

# AI assistant (Claude). Enabled when ANTHROPIC_API_KEY is set in the environment.
PACKWISE_ASSISTANT = {
    "MODEL": env("PACKWISE_ASSISTANT_MODEL", "claude-opus-5-5"),
    # Chat with simple tool sequencing; "medium" balances answer quality and latency.
    "EFFORT": env("PACKWISE_ASSISTANT_EFFORT", "medium"),
    "MAX_TOKENS": env_int("PACKWISE_ASSISTANT_MAX_TOKENS", 16000),
    "MAX_TOOL_ROUNDS": env_int("PACKWISE_ASSISTANT_MAX_TOOL_ROUNDS", 8),  # model calls per answer
    "MAX_TURNS": env_int("PACKWISE_ASSISTANT_MAX_TURNS", 30),  # user messages per conversation
    "MAX_MESSAGE_CHARS": env_int("PACKWISE_ASSISTANT_MAX_MESSAGE_CHARS", 2000),
}


# ---------------------------------------------------------------- logging

LOG_LEVEL = env("LOG_LEVEL", "INFO")
LOG_FORMAT = env("LOG_FORMAT", "text")  # "json" in production

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"()": "common.logging.JsonFormatter"},
        "text": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": LOG_FORMAT},
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "packwise": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        # Bots constantly send spoofed Host headers. The 400 response is correct, and a
        # traceback per request is noise (the Django docs recommend silencing this logger).
        "django.security.DisallowedHost": {"handlers": [], "level": "CRITICAL", "propagate": False},
    },
}

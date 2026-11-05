"""Local development settings. Never use these in production."""

from .base import *  # noqa: F403
from .base import REST_FRAMEWORK, database_config, env, env_bool, env_list

DEBUG = env_bool("DJANGO_DEBUG", True)
SECRET_KEY = env("DJANGO_SECRET_KEY", "django-insecure-dev-only-key-change-me")
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0,[::1]")

DATABASES = {
    "default": database_config("postgres://packwise:packwise@localhost:5432/packwise"),
}

REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
}

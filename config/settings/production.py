"""Production settings: fail fast on missing secrets and harden HTTP security.

Required environment variables: ``DJANGO_SECRET_KEY``, ``DATABASE_URL`` and
``DJANGO_ALLOWED_HOSTS`` (or ``RENDER_EXTERNAL_HOSTNAME``, which Render sets).
"""

from .base import *  # noqa: F403
from .base import LOGGING, database_config, env, env_bool, env_int, env_list, env_required

DEBUG = False
SECRET_KEY = env_required("DJANGO_SECRET_KEY")
# 40+ characters rejects placeholders such as "change-me" while accepting Render's
# generateValue secrets (base64 of 256 random bits = 44 characters).
if len(SECRET_KEY) < 40 or SECRET_KEY.startswith("django-insecure") or "change-me" in SECRET_KEY:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be a strong, random value (>= 40 characters).")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")
_render_host = env("RENDER_EXTERNAL_HOSTNAME")
if _render_host:
    ALLOWED_HOSTS.append(_render_host)
if not ALLOWED_HOSTS:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured("Set DJANGO_ALLOWED_HOSTS (comma-separated) for production.")

CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS") or [
    f"https://{host}" for host in ALLOWED_HOSTS if not host.startswith(".") and host != "*"
]

DATABASES = {"default": database_config()}

# ---- HTTPS: TLS is terminated by the platform's proxy (Render, a load balancer, ...).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
# (Health probes over plain HTTP are answered by common.middleware.HealthCheckMiddleware.)
SESSION_COOKIE_SECURE = SECURE_SSL_REDIRECT
CSRF_COOKIE_SECURE = SECURE_SSL_REDIRECT
SECURE_HSTS_SECONDS = env_int("DJANGO_SECURE_HSTS_SECONDS", 3600)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# includeSubDomains and preload are off on purpose: *.onrender.com is a shared parent domain we
# do not own, and preload requires includeSubDomains. Enable both on a custom domain.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

LOGGING["handlers"]["console"]["formatter"] = env("LOG_FORMAT", "json")

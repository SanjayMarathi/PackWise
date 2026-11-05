"""Production settings: fail fast on missing secrets and harden HTTP security.

Required environment variables: ``DJANGO_SECRET_KEY`` and ``DATABASE_URL``,
plus ``DJANGO_ALLOWED_HOSTS``. On Hugging Face Spaces the host is picked up
from ``SPACE_HOST``, which the platform sets.
"""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import LOGGING, MIDDLEWARE, database_config, env, env_bool, env_int, env_list, env_required

DEBUG = False
SECRET_KEY = env_required("DJANGO_SECRET_KEY")
# 40+ characters rejects placeholders such as "change-me" while still accepting standard
# generated secrets (e.g. base64 of 256 random bits = 44 characters).
if len(SECRET_KEY) < 40 or SECRET_KEY.startswith("django-insecure") or "change-me" in SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be a strong, random value (>= 40 characters).")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")
_platform_host = env("SPACE_HOST")  # e.g. "user-packwise.hf.space", set by Hugging Face Spaces
if _platform_host and _platform_host not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(_platform_host)
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("Set DJANGO_ALLOWED_HOSTS (comma-separated) for production.")

CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS") or [
    f"https://{host}" for host in ALLOWED_HOSTS if not host.startswith(".") and host != "*"
]

DATABASES = {"default": database_config()}

# ---- HTTPS: TLS is terminated by the platform's proxy (Hugging Face, a load balancer, ...).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Turn off only when the edge already forces HTTPS, so the app never sees plain HTTP from users.
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
# (Health probes over plain HTTP are answered by common.middleware.HealthCheckMiddleware.)
SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", True)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SECURE_HSTS_SECONDS = env_int("DJANGO_SECURE_HSTS_SECONDS", 3600)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Framing: DENY by default. To let a known site embed the app (the Hugging Face Space page
# wraps the app in an iframe), list its origins. X-Frame-Options cannot allow specific
# origins, so it is replaced by a CSP frame-ancestors header.
FRAME_ANCESTORS = env_list("DJANGO_FRAME_ANCESTORS")
if FRAME_ANCESTORS:
    MIDDLEWARE = [
        "common.middleware.FrameAncestorsMiddleware"
        if m == "django.middleware.clickjacking.XFrameOptionsMiddleware"
        else m
        for m in MIDDLEWARE
    ]

# includeSubDomains and preload are off on purpose: platform subdomains (*.hf.space) sit on a
# shared parent domain we do not own, and preload requires includeSubDomains.
# Enable both on a custom domain.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]
if FRAME_ANCESTORS:
    SILENCED_SYSTEM_CHECKS.append("security.W002")  # replaced by CSP frame-ancestors (see above)

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

LOGGING["handlers"]["console"]["formatter"] = env("LOG_FORMAT", "json")

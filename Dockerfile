# syntax=docker/dockerfile:1.7

# ---------- Stage 1: build wheels (compilers and caches never reach the runtime image)
FROM python:3.12-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt


# ---------- Stage 2: runtime
FROM python:3.12-slim-bookworm AS runtime

ARG APP_VERSION=dev
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production \
    APP_VERSION=${APP_VERSION} \
    PORT=8000 \
    WEB_CONCURRENCY=2

# Unprivileged user. uid 1000 matches the user that Hugging Face Spaces runs containers as.
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --home-dir /app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/* && rm -rf /wheels

# Code stays owned by root and is read-only to the runtime user: the app never writes to disk.
COPY . .

# collectstatic only needs settings that import cleanly; these throwaway values never reach runtime.
RUN DJANGO_SECRET_KEY=build-only-collectstatic-key-0123456789-0123456789-0123456789 \
    DATABASE_URL=postgres://build:build@localhost:5432/build \
    DJANGO_ALLOWED_HOSTS=localhost \
    python manage.py collectstatic --noinput --verbosity 0 \
    && chmod 755 docker/entrypoint.sh

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/api/health/', timeout=4)" || exit 1

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["web"]

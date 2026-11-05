#!/bin/sh
# Container entrypoint.
#   web      start Gunicorn (runs migrations first if RUN_MIGRATIONS=true)
#   migrate  apply migrations and exit (used by docker compose as a one-shot job)
#   *        run any other command, e.g. `python manage.py createsuperuser`
set -eu

run_migrations() {
    echo "entrypoint: applying database migrations"
    python manage.py migrate --noinput
    if [ "${SEED_DEMO_DATA:-false}" = "true" ]; then
        python manage.py seed_demo_data
    fi
}

case "${1:-web}" in
    web)
        # Platforms without a pre-deploy hook (e.g. Render's free tier) set RUN_MIGRATIONS=true.
        # Django migrations take locks, so concurrent starts are safe, though they wait on each other.
        if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
            run_migrations
        fi
        exec gunicorn config.wsgi:application \
            --bind "0.0.0.0:${PORT:-8000}" \
            --workers "${WEB_CONCURRENCY:-2}" \
            --threads "${GUNICORN_THREADS:-4}" \
            --timeout "${GUNICORN_TIMEOUT:-60}" \
            --access-logfile - \
            --error-logfile - \
            --forwarded-allow-ips "*" \
            --no-control-socket
        # --no-control-socket: Gunicorn >= 25.1 opens a runtime-control socket under $HOME,
        # which is read-only here; the platform, not gunicornc, manages the process.
        ;;
    migrate)
        run_migrations
        ;;
    *)
        exec "$@"
        ;;
esac

import logging

from django.conf import settings
from django.db import DatabaseError, connection

logger = logging.getLogger("packwise.health")


def health_status() -> tuple[dict, int]:
    """Return ``(payload, http_status)``. 503 when the database is unreachable."""
    try:
        # A trivial round-trip proves the connection is usable, not just configured.
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        database, code = "ok", 200
    except DatabaseError:
        logger.exception("health_check_database_unavailable")
        database, code = "unavailable", 503
    payload = {"status": "ok" if code == 200 else "degraded", "database": database, "version": settings.APP_VERSION}
    return payload, code

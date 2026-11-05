from django.http import JsonResponse

from .health import health_status

HEALTH_PATH = "/api/health/"


class HealthCheckMiddleware:
    """Answer the health probe before host validation and HTTPS redirects.

    Container and platform probes (Docker ``HEALTHCHECK``, load balancers)
    connect by IP. Their ``Host`` header (``127.0.0.1:8000``, ``10.x.x.x``)
    is not in ``ALLOWED_HOSTS``, and they speak plain HTTP behind the TLS
    proxy. Further down the stack Django would reply 400 or 301, and the
    platform would mark a healthy app as dead. Only this one read-only path
    is short-circuited. Every other request still gets full host validation.
    It must be the first entry in ``MIDDLEWARE``.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == HEALTH_PATH and request.method in ("GET", "HEAD"):
            payload, status = health_status()
            return JsonResponse(payload, status=status)
        return self.get_response(request)

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .health import health_status


@extend_schema(
    tags=["health"],
    summary="Liveness and database readiness probe",
    description="Served by `HealthCheckMiddleware` (before host validation). This view documents it in OpenAPI.",
    responses={
        200: inline_serializer(
            "Health",
            {
                "status": serializers.CharField(),
                "database": serializers.CharField(),
                "version": serializers.CharField(),
            },
        ),
        503: None,
    },
)
@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([])  # platform health probes must never be throttled
def health(request):
    payload, status = health_status()
    return Response(payload, status=status)

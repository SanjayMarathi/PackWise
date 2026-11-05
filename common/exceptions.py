"""Domain exceptions and the API-wide error envelope.

Every error response has the same shape::

    {"status": "error",
     "error": {"code": "validation_error", "message": "...", "details": {...}}}

Unexpected exceptions are logged with a traceback, but the client only sees a
generic message. Internal details never leak.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError, RestrictedError
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger("packwise.api")


class DomainError(Exception):
    """A business-rule violation raised by a service layer."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "domain_error"

    def __init__(self, message: str, *, code: str | None = None, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.default_code
        self.details = details


class ConflictError(DomainError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "conflict"


class ServiceUnavailableError(DomainError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = "service_unavailable"


class UnprocessableError(DomainError):
    """The request is well-formed but the resource's state prevents processing it."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_code = "unprocessable"


def error_payload(code: str, message: str, details: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"status": "error", "error": error}


def api_exception_handler(exc: Exception, context: dict) -> Response | None:
    if isinstance(exc, DomainError):
        return Response(error_payload(exc.code, exc.message, exc.details), status=exc.status_code)

    if isinstance(exc, (ProtectedError, RestrictedError)):
        return Response(
            error_payload("resource_in_use", "The resource is referenced by other records."),
            status=status.HTTP_409_CONFLICT,
        )

    if isinstance(exc, IntegrityError):
        # Typically a uniqueness race that the serializer validation could not see.
        logger.warning("integrity_error", extra={"view": _view_name(context), "error": str(exc)})
        return Response(
            error_payload("conflict", "The request conflicts with the current state of the data."),
            status=status.HTTP_409_CONFLICT,
        )

    if isinstance(exc, DjangoValidationError):
        exc = exceptions.ValidationError(detail=exc.message_dict if hasattr(exc, "error_dict") else exc.messages)
    elif isinstance(exc, Http404):
        exc = exceptions.NotFound()

    response = exception_handler(exc, context)
    if response is None:
        if settings.DEBUG:
            return None  # let Django render its debug page locally
        logger.exception("unhandled_api_error", extra={"view": _view_name(context)})
        return Response(
            error_payload("server_error", "An unexpected error occurred."),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if isinstance(exc, exceptions.ValidationError):
        response.data = error_payload("validation_error", "Request validation failed.", response.data)
    else:
        detail = response.data.get("detail", "") if isinstance(response.data, dict) else response.data
        code = getattr(exc, "default_code", "error")
        response.data = error_payload(str(code), str(detail))
    return response


def _view_name(context: dict) -> str | None:
    view = context.get("view")
    return type(view).__name__ if view is not None else None

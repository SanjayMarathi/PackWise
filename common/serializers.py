"""Serializer building blocks shared by the apps."""

from __future__ import annotations

from collections.abc import Mapping

from django.core.validators import RegexValidator
from rest_framework import serializers

CODE_VALIDATOR = RegexValidator(
    r"^[A-Z0-9][A-Z0-9._-]*$",
    "Use only letters, digits, '.', '_' or '-', starting with a letter or digit.",
)


class StrictFieldsMixin:
    """Reject unknown and read-only input keys instead of silently ignoring them.

    DRF quietly drops keys it does not recognise. That hides client bugs and
    makes mass-assignment attempts (e.g. sending ``"id"`` or ``"status"``)
    look as if they succeeded. Here they become a 400 with a precise message.
    """

    def to_internal_value(self, data):
        unexpected = {}
        if isinstance(data, Mapping):
            fields = self.fields  # type: ignore[attr-defined]
            for key in data:
                if key not in fields:
                    unexpected[key] = ["Unknown field."]
                elif fields[key].read_only:
                    unexpected[key] = ["This field is read-only."]
        # Run normal validation too, so the client sees every problem in one response.
        try:
            value = super().to_internal_value(data)  # type: ignore[misc]
        except serializers.ValidationError as exc:
            if unexpected and isinstance(exc.detail, dict):
                raise serializers.ValidationError({**exc.detail, **unexpected}) from exc
            raise
        if unexpected:
            raise serializers.ValidationError(unexpected)
        return value


class CodeField(serializers.CharField):
    """A business identifier (SKU, box code, order number) normalised to upper case.

    Normalisation happens in ``to_internal_value``. That runs *before*
    validators, so uniqueness is checked on the normalised value: ``abc-1``
    and ``ABC-1`` count as the same SKU.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.validators.append(CODE_VALIDATOR)

    def to_internal_value(self, data):
        return super().to_internal_value(data).strip().upper()

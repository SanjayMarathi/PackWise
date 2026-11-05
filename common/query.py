from rest_framework.exceptions import ValidationError

_TRUE = {"true", "1", "yes"}
_FALSE = {"false", "0", "no"}


def parse_bool_param(params, name: str) -> bool | None:
    """Parse an optional boolean query parameter. Invalid values are a 400, not ignored."""
    raw = params.get(name)
    if raw is None or raw == "":
        return None
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValidationError({name: [f"Expected true or false, got {raw!r}."]})

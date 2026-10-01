"""Helpers that translate validation failures into template-friendly field errors."""

from __future__ import annotations

from pydantic import ValidationError as PydanticValidationError

from app.errors import ValidationError

_LABELS = {
    "string_too_short": "is too short",
    "string_too_long": "is too long",
    "greater_than": "must be greater than 0",
    "greater_than_equal": "is not high enough",
    "less_than_equal": "is too high",
    "int_parsing": "must be a whole number",
    "literal_error": "is not a recognised option",
    "value_error": "is not valid",
    "min_length": "is too short",
    "max_length": "is too long",
}


def field_errors(exc: PydanticValidationError | ValidationError) -> dict[str, list[str]]:
    """Map pydantic errors onto ``{field: [message]}`` for form rendering."""
    errors: dict[str, list[str]] = {}
    if isinstance(exc, ValidationError):
        return dict(exc.field_errors)
    for item in exc.errors():
        field = _field_name(item.get("loc", ()))
        message = _message_for(item)
        errors.setdefault(field, []).append(message)
    return errors


def _field_name(loc: object) -> str:
    parts = [str(part) for part in (loc or ()) if not isinstance(part, int)]
    return parts[-1] if parts else "form"


def _message_for(item: dict[str, object]) -> str:
    error_type = str(item.get("type", ""))
    context = item.get("context")
    if isinstance(context, dict):
        if "min_length" in context and error_type in {"string_too_short", "min_length"}:
            return f"is too short (minimum {context['min_length']} characters)"
        if "max_length" in context and error_type in {"string_too_long", "max_length"}:
            return f"is too long (maximum {context['max_length']} characters)"
        if "gt" in context:
            return f"must be greater than {context['gt']}"
        if "ge" in context:
            return f"must be at least {context['ge']}"
    if error_type == "value_error":
        # Custom validators raise with the reason already embedded in msg.
        return str(item.get("msg", "is not valid"))
    return _LABELS.get(error_type, str(item.get("msg", "is not valid")))

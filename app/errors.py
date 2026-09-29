"""Application error types.

Every expected failure surfaces as an :class:`AppError` subclass so routers,
templates, and the exception handlers share one shape.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for handled application failures."""

    status_code: int = 500
    default_message: str = "Something went wrong."

    def __init__(
        self,
        message: str | None = None,
        *,
        field_errors: dict[str, list[str]] | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or self.default_message)
        self.message = message or self.default_message
        self.field_errors: dict[str, list[str]] = field_errors or {}
        self.context: dict[str, Any] = context or {}

    def add_field_error(self, field: str, message: str) -> None:
        self.field_errors.setdefault(field, []).append(message)


class ValidationError(AppError):
    status_code = 422
    default_message = "The submitted data is not valid."


class AuthenticationError(AppError):
    status_code = 401
    default_message = "You need to sign in to do that."


class PermissionDeniedError(AppError):
    status_code = 403
    default_message = "You do not have access to this resource."


class NotFoundError(AppError):
    status_code = 404
    default_message = "The requested resource was not found."


class ConflictError(AppError):
    status_code = 409
    default_message = "This action conflicts with the current state."


class ExternalServiceError(AppError):
    status_code = 502
    default_message = "The marketplace data service is unavailable. Please try again shortly."


__all__ = [
    "AppError",
    "AuthenticationError",
    "ConflictError",
    "ExternalServiceError",
    "NotFoundError",
    "PermissionDeniedError",
    "ValidationError",
]

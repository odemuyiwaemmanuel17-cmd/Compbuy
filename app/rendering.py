"""Shared rendering helpers for the server-side rendered UI."""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

from app.errors import AppError, AuthenticationError
from app.session_store import drain_flash
from app.templating import MarketplaceTemplates

LOGIN_PATH = "/auth/login"
MAX_NEXT_LENGTH = 200


def templates_for(request: Request) -> MarketplaceTemplates:
    return request.app.state.templates  # type: ignore[return-value]


def render(request: Request, template_name: str, context: dict[str, Any]) -> HTMLResponse:
    """Render a template with the navigation, flash, and error context."""
    payload: dict[str, Any] = {
        "flash_messages": drain_flash(request),
        "current_path": request.url.path,
        "app_error": None,
        "field_errors": {},
    }
    payload.update(context)
    return templates_for(request).TemplateResponse(request=request, name=template_name, context=payload)


def render_form_error(
    request: Request,
    template_name: str,
    context: dict[str, Any],
    *,
    message: str,
    field_errors: dict[str, list[str]] | None = None,
) -> HTMLResponse:
    """Re-render a form with a banner message and per-field errors preserved."""
    payload = dict(context)
    payload["app_error"] = message
    payload["field_errors"] = field_errors or {}
    response = render(request, template_name, payload)
    response.status_code = 422
    return response


def error_response(request: Request, error: AppError) -> HTMLResponse | RedirectResponse:
    """Render an error page, or bounce anonymous visitors to the sign-in form."""
    if isinstance(error, AuthenticationError):
        return to_login(request)
    status = error.status_code
    template = "errors/404.html" if status == 404 else "errors/error.html"
    response = render(
        request,
        template,
        {
            "app_error": error.message,
            "field_errors": error.field_errors,
            "status_code": status,
        },
    )
    response.status_code = status
    return response


def to_login(request: Request) -> RedirectResponse:
    """Redirect to sign-in, preserving the originally requested path."""
    next_path = request.url.path
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    if len(next_path) > MAX_NEXT_LENGTH:
        next_path = "/"
    return RedirectResponse(f"{LOGIN_PATH}?next={next_path}", status_code=303)


def safe_next(target: str | None) -> str:
    """Only ever follow a same-site relative path, to block open redirects."""
    if not target:
        return "/"
    collapsed = target.strip()
    if not collapsed.startswith("/") or collapsed.startswith("//") or "://" in collapsed:
        return "/"
    return collapsed[:MAX_NEXT_LENGTH]

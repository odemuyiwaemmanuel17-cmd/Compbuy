"""Server-side session helpers.

Sessions live in a signed, httpOnly, SameSite cookie managed by Starlette's
``SessionMiddleware`` (backed by ``itsdangerous``). Supabase tokens are stored
there because the templated UI performs server-side rendering only, so they are
never exposed to browser JavaScript. HTTPS is required in production.
"""

from __future__ import annotations

from typing import Any, TypedDict

from starlette.requests import Request

from app.db import AuthSession

USER_ID_KEY = "user_id"
USER_EMAIL_KEY = "user_email"
ACCESS_TOKEN_KEY = "supabase_access_token"
REFRESH_TOKEN_KEY = "supabase_refresh_token"
FLASH_KEY = "flash_messages"

MAX_FLASH_MESSAGES = 5


class FlashMessage(TypedDict):
    category: str
    text: str


def store_auth_session(request: Request, auth: AuthSession) -> None:
    """Write the verified Supabase identity and tokens into the session."""
    request.session[USER_ID_KEY] = auth.user.id
    request.session[USER_EMAIL_KEY] = auth.user.email
    request.session[ACCESS_TOKEN_KEY] = auth.access_token
    request.session[REFRESH_TOKEN_KEY] = auth.refresh_token


def session_user_id(request: Request) -> str | None:
    value = request.session.get(USER_ID_KEY)
    return str(value) if value else None


def session_access_token(request: Request) -> str | None:
    value = request.session.get(ACCESS_TOKEN_KEY)
    return str(value) if value else None


def is_signed_in(request: Request) -> bool:
    return session_user_id(request) is not None


def flash(request: Request, text: str, *, category: str = "info") -> None:
    """Queue a one-shot message for the next rendered page."""
    messages: list[Any] = list(request.session.get(FLASH_KEY) or [])
    messages.append({"category": category, "text": text})
    request.session[FLASH_KEY] = messages[-MAX_FLASH_MESSAGES:]


def drain_flash(request: Request) -> list[FlashMessage]:
    """Return and remove queued flash messages."""
    raw = request.session.pop(FLASH_KEY, None)
    if not raw:
        return []
    drained: list[FlashMessage] = []
    for item in raw:
        if isinstance(item, dict) and item.get("text"):
            drained.append(
                {"category": str(item.get("category", "info")), "text": str(item["text"])}
            )
    return drained

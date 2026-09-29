"""Supabase access layer.

The rest of the application depends on the narrow ``Gateway``/``Query``
protocols declared here rather than on ``supabase-py`` directly. That keeps one
integration seam to configure in production and lets the test suite substitute
an in-memory implementation without touching business logic.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import anyio

from app.config import Settings
from app.errors import (
    AppError,
    AuthenticationError,
    ConflictError,
    ExternalServiceError,
    NotFoundError,
    ValidationError,
)


@dataclass(frozen=True)
class QueryResult:
    """Normalised result of a database call."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    count: int | None = None

    @property
    def first(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)


@runtime_checkable
class Query(Protocol):
    """Chainable, terminal-``execute()`` query builder."""

    def select(self, columns: str = "*", *, count: str | None = None) -> "Query": ...

    def insert(self, values: dict[str, Any] | list[dict[str, Any]]) -> "Query": ...

    def upsert(self, values: dict[str, Any]) -> "Query": ...

    def update(self, values: dict[str, Any]) -> "Query": ...

    def delete(self) -> "Query": ...

    def eq(self, column: str, value: Any) -> "Query": ...

    def neq(self, column: str, value: Any) -> "Query": ...

    def in_(self, column: str, values: Iterable[Any]) -> "Query": ...

    def gte(self, column: str, value: Any) -> "Query": ...

    def lte(self, column: str, value: Any) -> "Query": ...

    def ilike(self, column: str, pattern: str) -> "Query": ...

    def or_ilike(self, columns: Sequence[str], pattern: str) -> "Query": ...

    def order(self, column: str, *, descending: bool = False) -> "Query": ...

    def limit(self, amount: int) -> "Query": ...

    def range(self, start: int, end: int) -> "Query": ...

    def execute(self) -> QueryResult: ...


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str


@dataclass(frozen=True)
class AuthSession:
    user: AuthUser
    access_token: str
    refresh_token: str


@runtime_checkable
class AuthGateway(Protocol):
    def sign_up(self, email: str, password: str) -> AuthSession: ...

    def sign_in(self, email: str, password: str) -> AuthSession: ...

    def sign_out(self, access_token: str) -> None: ...

    def user_from_token(self, access_token: str) -> AuthUser | None: ...


@runtime_checkable
class Gateway(Protocol):
    """Database plus auth entrypoint."""

    def table(self, name: str) -> Query: ...

    @property
    def auth(self) -> AuthGateway: ...


class SupabaseQuery:
    """Adapter turning a ``postgrest`` request builder into a ``Query``."""

    __slots__ = ("_builder", "_resource")

    def __init__(self, builder: Any, *, resource: str = "record") -> None:
        self._builder = builder
        self._resource = resource

    def select(self, columns: str = "*", *, count: str | None = None) -> "SupabaseQuery":
        if count is None:
            self._builder = self._builder.select(columns)
        else:
            self._builder = self._builder.select(columns, count=count)  # type: ignore[arg-type]
        return self

    def insert(self, values: dict[str, Any] | list[dict[str, Any]]) -> "SupabaseQuery":
        self._builder = self._builder.insert(values)
        return self

    def upsert(self, values: dict[str, Any], *, on_conflict: str | None = None) -> "SupabaseQuery":
        if on_conflict is None:
            self._builder = self._builder.upsert(values)
        else:
            self._builder = self._builder.upsert(values, on_conflict=on_conflict)
        return self

    def update(self, values: dict[str, Any]) -> "SupabaseQuery":
        self._builder = self._builder.update(values)
        return self

    def delete(self) -> "SupabaseQuery":
        # ``supabase-py`` defaults to ``return=representation``, so the deleted
        # rows come back in ``data`` — matching the in-memory test gateway.
        self._builder = self._builder.delete()
        return self

    def eq(self, column: str, value: Any) -> "SupabaseQuery":
        self._builder = self._builder.eq(column, value)
        return self

    def neq(self, column: str, value: Any) -> "SupabaseQuery":
        self._builder = self._builder.neq(column, value)
        return self

    def in_(self, column: str, values: Iterable[Any]) -> "SupabaseQuery":
        self._builder = self._builder.in_(column, list(values))
        return self

    def gte(self, column: str, value: Any) -> "SupabaseQuery":
        self._builder = self._builder.gte(column, value)
        return self

    def lte(self, column: str, value: Any) -> "SupabaseQuery":
        self._builder = self._builder.lte(column, value)
        return self

    def ilike(self, column: str, pattern: str) -> "SupabaseQuery":
        self._builder = self._builder.ilike(column, pattern)
        return self

    def or_ilike(self, columns: Sequence[str], pattern: str) -> "SupabaseQuery":
        clauses = ",".join(f"{column}.ilike.{pattern}" for column in columns)
        self._builder = self._builder.or_(clauses)
        return self

    def order(self, column: str, *, descending: bool = False) -> "SupabaseQuery":
        self._builder = self._builder.order(column, desc=descending)
        return self

    def limit(self, amount: int) -> "SupabaseQuery":
        self._builder = self._builder.limit(amount)
        return self

    def range(self, start: int, end: int) -> "SupabaseQuery":
        self._builder = self._builder.range(start, end)
        return self

    def execute(self) -> QueryResult:
        try:
            response = self._builder.execute()
        except AppError:
            raise
        except Exception as exc:
            # PostgREST raises raw exceptions for constraint violations, RLS
            # denials, and outages. Translate them so the HTTP layer reports a
            # meaningful 4xx/502 instead of an unhandled 500.
            raise translate_supabase_error(exc, resource=self._resource) from exc
        rows = list(getattr(response, "data", None) or [])
        raw_count = getattr(response, "count", None)
        return QueryResult(rows=rows, count=int(raw_count) if raw_count is not None else None)


class SupabaseAuth:
    """Auth against the Supabase project using the anon key."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def sign_up(self, email: str, password: str) -> AuthSession:
        response = self._client.auth.sign_up({"email": email, "password": password})
        return self._to_session(response, fallback_email=email)

    def sign_in(self, email: str, password: str) -> AuthSession:
        response = self._client.auth.sign_in_with_password({"email": email, "password": password})
        return self._to_session(response, fallback_email=email)

    def sign_out(self, access_token: str) -> None:
        # ``access_token`` is required by the AuthGateway protocol (the in-memory
        # implementation revokes that token); the Supabase server invalidates the
        # session from its own cookie state. Sign-out is best-effort by design:
        # the local session is destroyed even if this call fails.
        with contextlib.suppress(Exception):
            self._client.auth.sign_out()

    def user_from_token(self, access_token: str) -> AuthUser | None:
        response = self._client.auth.get_user(access_token)
        user = getattr(response, "user", None)
        if user is None or not getattr(user, "id", None):
            return None
        return AuthUser(id=str(user.id), email=str(getattr(user, "email", "") or ""))

    def _to_session(self, response: Any, *, fallback_email: str) -> AuthSession:
        session = getattr(response, "session", None)
        user = getattr(response, "user", None)
        if session is None or not getattr(session, "access_token", None):
            # Confirmed-email flows return a user but no session.
            if user is not None and getattr(user, "id", None):
                raise AuthenticationError(
                    "Check your inbox to confirm your email address before signing in."
                )
            raise AuthenticationError("We could not sign you in with those details.")
        resolved_user = user or getattr(session, "user", None)
        user_id = str(getattr(resolved_user, "id", "") or "")
        if not user_id:
            raise ExternalServiceError("Supabase returned a session without a user id.")
        email = str(getattr(resolved_user, "email", "") or fallback_email)
        return AuthSession(
            user=AuthUser(id=user_id, email=email),
            access_token=str(session.access_token),
            refresh_token=str(getattr(session, "refresh_token", "") or ""),
        )


_TABLE_NOUNS = {
    "profiles": "profile",
    "listings": "listing",
    "offers": "offer",
    "watchlist": "watchlist entry",
    "conversations": "conversation",
    "messages": "message",
}


class SupabaseGateway:
    """Live gateway backed by ``supabase.create_client``."""

    def __init__(self, settings: Settings) -> None:
        if not settings.has_supabase_credentials:
            raise ExternalServiceError(
                "Supabase is not configured. Set SUPABASE_URL and SUPABASE_ANON_KEY "
                "in your .env file."
            )
        # Imported lazily so credential-free environments never pay the cost.
        from supabase import create_client

        supabase_url = settings.supabase_url
        anon_key = settings.supabase_anon_key
        if supabase_url is None or anon_key is None:
            raise ExternalServiceError(
                "Supabase is not configured. Set SUPABASE_URL and SUPABASE_ANON_KEY "
                "in your .env file."
            )

        # Reads and writes that must not be filtered by RLS (server-side rendering
        # holds no end-user JWT) use the service role key; authorisation is
        # enforced in the service layer by owner id.
        if settings.supabase_service_role_key:
            self._data_client = create_client(supabase_url, settings.supabase_service_role_key)
            # Auth operations must run with the anon key, never the service role.
            self._auth_client = create_client(supabase_url, anon_key)
        else:
            self._data_client = create_client(supabase_url, anon_key)
            self._auth_client = self._data_client
        self._auth = SupabaseAuth(self._auth_client)

    def table(self, name: str) -> Query:
        return SupabaseQuery(
            self._data_client.table(name), resource=_TABLE_NOUNS.get(name, name.replace("_", " "))
        )

    @property
    def auth(self) -> AuthGateway:
        return self._auth


def translate_supabase_error(error: Exception, *, resource: str) -> AppError:
    """Map client exceptions onto application errors."""
    message = str(error)
    lowered = message.lower()
    if "duplicate key" in lowered or "already exists" in lowered:
        return ConflictError(f"That {resource} already exists.")
    if "not found" in lowered or "does not exist" in lowered:
        return NotFoundError(f"The {resource} you are looking for does not exist.")
    if "invalid login credentials" in lowered or "log in attempted" in lowered:
        return AuthenticationError("Email or password is incorrect.")
    if "already registered" in lowered or "user already" in lowered:
        return ConflictError("An account with that email already exists.")
    if "password should be" in lowered or "weak password" in lowered:
        return ValidationError("Please choose a stronger password (10+ characters).")
    if "failed to fetch" in lowered or "connection" in lowered or "timeout" in lowered:
        return ExternalServiceError()
    return ExternalServiceError(f"The marketplace data service rejected that request: {message}")


_gateway_lock = threading.RLock()
_active_gateway: Gateway | None = None


def set_gateway(gateway: Gateway | None) -> Gateway | None:
    """Install a gateway and return the previous one (test seam and boot hook)."""
    global _active_gateway
    with _gateway_lock:
        previous = _active_gateway
        _active_gateway = gateway
        return previous


def get_gateway() -> Gateway:
    """Return the active gateway."""
    with _gateway_lock:
        if _active_gateway is None:
            raise ExternalServiceError("The Supabase gateway has not been initialised.")
        return _active_gateway


def gateway_ready() -> bool:
    with _gateway_lock:
        return _active_gateway is not None


async def run_query(query: Query) -> QueryResult:
    """Execute a blocking Supabase call off the event loop."""
    return await anyio.to_thread.run_sync(query.execute)


async def run_in_thread(func, *args: Any, **kwargs: Any) -> Any:
    """Run a blocking Supabase auth call off the event loop."""
    return await anyio.to_thread.run_sync(lambda: func(*args, **kwargs))


__all__ = [
    "AuthGateway",
    "AuthSession",
    "AuthUser",
    "Gateway",
    "Query",
    "QueryResult",
    "SupabaseGateway",
    "get_gateway",
    "gateway_ready",
    "run_in_thread",
    "run_query",
    "set_gateway",
    "translate_supabase_error",
]

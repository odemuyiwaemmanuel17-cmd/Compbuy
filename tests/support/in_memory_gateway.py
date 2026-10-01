"""An in-memory implementation of the Supabase ``Gateway`` protocol.

It mirrors the semantics the application relies on from PostgREST — filter
chains, ``count="exact"`` totals, representation-returning writes, and upsert
conflict targets — so the service and router layers can be exercised without
any Supabase credentials or network access.
"""

from __future__ import annotations

import copy
import re
import threading
import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from app.database import AuthSession, AuthUser, QueryResult


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _comparable(value: Any) -> Any:
    """Coerce form-ish strings so numeric comparisons behave like Postgres."""
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if re.fullmatch(r"-?\d+(\.\d+)?", text or ""):
            return float(text)
    return value


def _pattern_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a PostgREST ``ilike`` pattern (``%`` wildcards) into a regex."""
    escaped = re.escape(pattern)
    for token, regex_part in ((r"\*", ".*"), (r"%", ".*"), (r"_", ".")):
        escaped = escaped.replace(token, regex_part)
    return re.compile(f"^{escaped}$", re.IGNORECASE)


class Filter:
    __slots__ = ("column", "kind", "value")

    def __init__(self, kind: str, column: str, value: Any) -> None:
        self.kind = kind
        self.column = column
        self.value = value

    def matches(self, row: dict[str, Any]) -> bool:
        actual = row.get(self.column)
        if self.kind == "or_ilike":
            columns, pattern = self.value
            needle = pattern.strip("%")
            return any(needle.lower() in str(row.get(col, "") or "").lower() for col in columns)

        if self.kind in {"gte", "lte"} and (actual is None or self.value is None):
            return False

        if self.kind == "eq":
            return actual == self.value
        if self.kind == "neq":
            return actual != self.value
        if self.kind == "in":
            return actual in set(self.value)
        if self.kind == "gte":
            return _comparable(actual) >= _comparable(self.value)
        if self.kind == "lte":
            return _comparable(actual) <= _comparable(self.value)
        if self.kind == "ilike":
            return _pattern_to_regex(self.value).match(str(actual if actual is not None else "")) is not None
        raise ValueError(f"Unsupported filter kind: {self.kind}")


class InMemoryQuery:
    """Chainable query that evaluates against the in-memory store."""

    def __init__(self, gateway: InMemoryGateway, table: str) -> None:
        self._gateway = gateway
        self._table = table
        self._operation = "select"
        self._payload: dict[str, Any] | list[dict[str, Any]] | None = None
        self._filters: list[Filter] = []
        self._orders: list[tuple[str, bool]] = []
        self._limit: int | None = None
        self._window: tuple[int, int] | None = None
        self._want_count = False
        self._conflict_columns: tuple[str, ...] = ("id",)

    # ------------------------------------------------------------------ chain

    def select(self, columns: str = "*", *, count: str | None = None) -> InMemoryQuery:
        self._operation = "select"
        self._want_count = count is not None
        return self

    def insert(self, values: dict[str, Any] | list[dict[str, Any]]) -> InMemoryQuery:
        self._operation = "insert"
        self._payload = copy.deepcopy(values)
        return self

    def upsert(self, values: dict[str, Any], *, on_conflict: str | None = None) -> InMemoryQuery:
        self._operation = "upsert"
        self._payload = copy.deepcopy(values)
        self._conflict_columns = tuple(
            part.strip() for part in (on_conflict or "id").split(",") if part.strip()
        )
        return self

    def update(self, values: dict[str, Any]) -> InMemoryQuery:
        self._operation = "update"
        self._payload = copy.deepcopy(values)
        return self

    def delete(self) -> InMemoryQuery:
        self._operation = "delete"
        return self

    def eq(self, column: str, value: Any) -> InMemoryQuery:
        return self._add("eq", column, value)

    def neq(self, column: str, value: Any) -> InMemoryQuery:
        return self._add("neq", column, value)

    def in_(self, column: str, values: Iterable[Any]) -> InMemoryQuery:
        return self._add("in", column, list(values))

    def gte(self, column: str, value: Any) -> InMemoryQuery:
        return self._add("gte", column, value)

    def lte(self, column: str, value: Any) -> InMemoryQuery:
        return self._add("lte", column, value)

    def ilike(self, column: str, pattern: str) -> InMemoryQuery:
        return self._add("ilike", column, pattern)

    def or_ilike(self, columns: Iterable[str], pattern: str) -> InMemoryQuery:
        return self._add("or_ilike", "*", (tuple(columns), pattern))

    def order(self, column: str, *, descending: bool = False) -> InMemoryQuery:
        self._orders.append((column, descending))
        return self

    def limit(self, amount: int) -> InMemoryQuery:
        self._limit = amount
        return self

    def range(self, start: int, end: int) -> InMemoryQuery:
        self._window = (start, end)
        return self

    def _add(self, kind: str, column: str, value: Any) -> InMemoryQuery:
        self._filters.append(Filter(kind, column, value))
        return self

    # ---------------------------------------------------------------- execute

    def execute(self) -> QueryResult:
        handler = {
            "select": self._do_select,
            "insert": self._do_insert,
            "upsert": self._do_upsert,
            "update": self._do_update,
            "delete": self._do_delete,
        }[self._operation]
        return handler()

    def _matching(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [row for row in rows if all(filter_.matches(row) for filter_ in self._filters)]

    def _sorted(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Apply in reverse so the first order() call is the primary key.
        for column, descending in reversed(self._orders):
            rows.sort(
                key=lambda row, col=column: _sort_key(row.get(col)),
                reverse=descending,
            )
        return rows

    def _trimmed(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self._window is not None:
            start, end = self._window
            rows = rows[start : end + 1]
        if self._limit is not None:
            rows = rows[: self._limit]
        return rows

    def _do_select(self) -> QueryResult:
        with self._gateway.lock:
            rows = self._matching(self._gateway.raw(self._table))
            total = len(rows)
            page = self._trimmed(self._sorted(rows))
            return QueryResult(
                rows=copy.deepcopy(page),
                count=total if self._want_count else None,
            )

    def _do_insert(self) -> QueryResult:
        payload = self._payload or []
        items = payload if isinstance(payload, list) else [payload]
        created = [self._gateway.append(self._table, dict(item)) for item in items]
        return QueryResult(rows=copy.deepcopy(created))

    def _do_upsert(self) -> QueryResult:
        payload = self._payload or {}
        items = payload if isinstance(payload, list) else [payload]
        affected: list[dict[str, Any]] = []
        for item in items:
            row = dict(item)
            with self._gateway.lock:
                existing = self._find_conflict(row)
                if existing is None:
                    affected.append(self._gateway.append(self._table, row))
                else:
                    existing.update(row)
                    self._stamp(existing)
                    affected.append(copy.deepcopy(existing))
        return QueryResult(rows=affected)

    def _find_conflict(self, row: dict[str, Any]) -> dict[str, Any] | None:
        for candidate in self._gateway.raw(self._table):
            if all(candidate.get(col) is not None and candidate.get(col) == row.get(col) for col in self._conflict_columns):
                return candidate
        return None

    def _do_update(self) -> QueryResult:
        values = dict(self._payload or {})
        affected: list[dict[str, Any]] = []
        with self._gateway.lock:
            for row in self._matching(self._gateway.raw(self._table)):
                for column, value in values.items():
                    if column != "id":
                        row[column] = value
                self._stamp(row)
                affected.append(copy.deepcopy(row))
        return QueryResult(rows=affected)

    def _do_delete(self) -> QueryResult:
        removed: list[dict[str, Any]] = []
        with self._gateway.lock:
            keep: list[dict[str, Any]] = []
            for row in self._gateway.raw(self._table):
                if all(filter_.matches(row) for filter_ in self._filters):
                    removed.append(copy.deepcopy(row))
                else:
                    keep.append(row)
            self._gateway.replace(self._table, keep)
        return QueryResult(rows=removed)

    @staticmethod
    def _stamp(row: dict[str, Any]) -> None:
        row["updated_at"] = _now()


def _sort_key(value: Any) -> tuple[int, float | str]:
    """Order values without tripping over ``None`` and numeric strings."""
    if value is None:
        return (0, 0.0)
    if isinstance(value, bool):
        return (1, float(value))
    if isinstance(value, (int, float)):
        return (1, float(value))
    if isinstance(value, str):
        try:
            return (1, float(value))
        except ValueError:
            return (2, value.lower())
    return (2, str(value))


class InMemoryAuth:
    """Email/password auth with the same contract as ``SupabaseAuth``."""

    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.tokens: dict[str, AuthUser] = {}

    def sign_up(self, email: str, password: str) -> AuthSession:
        key = email.strip().lower()
        if key in self.users:
            raise ValueError("User already registered")
        if len(password) < 10:
            raise ValueError("Password should be at least 10 characters")
        user = {
            "id": str(uuid.uuid4()),
            "email": key,
            "password": password,
            "confirmed_at": _now(),
        }
        self.users[key] = user
        return self._session(user)

    def sign_in(self, email: str, password: str) -> AuthSession:
        key = email.strip().lower()
        user = self.users.get(key)
        if user is None or user["password"] != password:
            raise ValueError("Invalid Login Credentials")
        return self._session(user)

    def sign_out(self, access_token: str) -> None:
        self.tokens.pop(access_token, None)

    def user_from_token(self, access_token: str) -> AuthUser | None:
        return self.tokens.get(access_token)

    def _session(self, user: dict[str, Any]) -> AuthSession:
        auth_user = AuthUser(id=user["id"], email=user["email"])
        access_token = f"access-{uuid.uuid4()}"
        self.tokens[access_token] = auth_user
        return AuthSession(
            user=auth_user,
            access_token=access_token,
            refresh_token=f"refresh-{uuid.uuid4()}",
        )


class InMemoryGateway:
    """Drop-in replacement for :class:`app.database.SupabaseGateway`."""

    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.lock = threading.RLock()
        self.auth = InMemoryAuth()

    # ------------------------------------------------------------- test hooks

    def raw(self, table: str) -> list[dict[str, Any]]:
        return self._tables[table]

    def rows(self, table: str) -> list[dict[str, Any]]:
        with self.lock:
            return copy.deepcopy(self._tables[table])

    def replace(self, table: str, rows: list[dict[str, Any]]) -> None:
        self._tables[table] = rows

    def seed(self, table: str, rows: Iterable[dict[str, Any]]) -> None:
        with self.lock:
            self._tables[table].extend(copy.deepcopy(list(rows)))

    # ---------------------------------------------------------------- gateway

    def table(self, name: str) -> InMemoryQuery:
        return InMemoryQuery(self, name)

    def append(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            stored: dict[str, Any] = dict(row)
            if not stored.get("id"):
                stored["id"] = str(uuid.uuid4())
            if not stored.get("created_at"):
                stored["created_at"] = _now()
            if not stored.get("updated_at"):
                stored["updated_at"] = stored["created_at"]
            if table == "listings":
                stored.setdefault("status", "draft")
                stored.setdefault("image_urls", [])
                stored.setdefault("currency", "USD")
                stored.setdefault("annual_profit", None)
                stored.setdefault("established_year", None)
            if table == "offers":
                stored.setdefault("status", "pending")
            self._tables[table].append(stored)
            return copy.deepcopy(stored)

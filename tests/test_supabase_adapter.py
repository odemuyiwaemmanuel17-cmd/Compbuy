"""Adapter contract tests for the live Supabase gateway.

The integration suite uses an in-memory double, so the class that actually
translates our ``Query`` protocol into ``supabase-py`` builder calls would
otherwise be untested until a live project is configured. These tests record
the exact method/argument shape sent to ``supabase-py``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.database import (
    QueryResult,
    SupabaseAuth,
    SupabaseQuery,
    translate_supabase_error,
)
from app.errors import (
    AuthenticationError,
    ConflictError,
    ExternalServiceError,
    NotFoundError,
    ValidationError,
)


class RecordingBuilder:
    """Stand-in for a postgrest request builder that records every call."""

    def __init__(self, calls: list[tuple], *, response=None, error: Exception | None = None) -> None:
        self.calls = calls
        self.response = response if response is not None else SimpleNamespace(data=[], count=None)
        self.error = error

    def _next(self, name: str, args, kwargs):
        self.calls.append((name, args, kwargs))
        return RecordingBuilder(self.calls, response=self.response, error=self.error)

    def select(self, *columns, count=None, head=None):
        return self._next("select", columns, {"count": count, "head": head})

    def insert(self, json, **kwargs):
        return self._next("insert", (json,), kwargs)

    def upsert(self, json, **kwargs):
        return self._next("upsert", (json,), kwargs)

    def update(self, json, **kwargs):
        return self._next("update", (json,), kwargs)

    def delete(self, **kwargs):
        return self._next("delete", (), kwargs)

    def eq(self, column, value):
        return self._next("eq", (column, value), {})

    def neq(self, column, value):
        return self._next("neq", (column, value), {})

    def in_(self, column, values):
        return self._next("in_", (column, values), {})

    def gte(self, column, value):
        return self._next("gte", (column, value), {})

    def lte(self, column, value):
        return self._next("lte", (column, value), {})

    def ilike(self, column, pattern):
        return self._next("ilike", (column, pattern), {})

    def or_(self, expression):
        return self._next("or_", (expression,), {})

    def order(self, column, *, desc=False, nulls_first=True):
        return self._next("order", (column,), {"desc": desc})

    def limit(self, amount):
        return self._next("limit", (amount,), {})

    def range(self, start, end):
        return self._next("range", (start, end), {})

    def execute(self):
        self.calls.append(("execute", (), {}))
        if self.error is not None:
            raise self.error
        return self.response


def names(calls: list[tuple]) -> list[str]:
    return [name for name, _, _ in calls]


def call(calls: list[tuple], name: str) -> tuple:
    return next(entry for entry in calls if entry[0] == name)


# ------------------------------------------------------------------- query shape

def test_select_without_count_omits_the_count_kwarg() -> None:
    calls: list[tuple] = []
    SupabaseQuery(RecordingBuilder(calls)).select("id, title").execute()

    assert names(calls) == ["select", "execute"]
    assert call(calls, "select")[1] == ("id, title",)
    assert call(calls, "select")[2] == {"count": None, "head": None}


def test_select_with_exact_count_forwards_it() -> None:
    calls: list[tuple] = []
    SupabaseQuery(RecordingBuilder(calls)).select("*", count="exact").execute()

    assert call(calls, "select")[2]["count"] == "exact"


def test_filter_chain_maps_to_postgrest_methods() -> None:
    calls: list[tuple] = []
    (
        SupabaseQuery(RecordingBuilder(calls))
        .select("*")
        .eq("status", "published")
        .neq("seller_id", "s1")
        .in_("id", ("a", "b"))
        .gte("asking_price", 1000)
        .lte("asking_price", 5000)
        .ilike("title", "%saas%")
        .execute()
    )

    assert names(calls) == [
        "select",
        "eq",
        "neq",
        "in_",
        "gte",
        "lte",
        "ilike",
        "execute",
    ]
    # A generator must be materialised: postgrest joins values into a query string.
    assert call(calls, "in_")[1][1] == ["a", "b"]


def test_or_ilike_builds_a_single_postgrest_or_expression() -> None:
    calls: list[tuple] = []
    SupabaseQuery(RecordingBuilder(calls)).select("*").or_ilike(
        ("title", "one_liner", "description"), "%ledgerly%"
    ).execute()

    assert call(calls, "or_")[1][0] == "title.ilike.%ledgerly%,one_liner.ilike.%ledgerly%,description.ilike.%ledgerly%"


def test_order_range_and_limit_use_the_builder_keyword_form() -> None:
    calls: list[tuple] = []
    SupabaseQuery(RecordingBuilder(calls)).select("*").order("created_at", descending=True).range(24, 35).limit(12).execute()

    assert call(calls, "order") == ("order", ("created_at",), {"desc": True})
    assert call(calls, "range")[1] == (24, 35)
    assert call(calls, "limit")[1] == (12,)


def test_ascending_order_is_forwarded_as_desc_false() -> None:
    calls: list[tuple] = []
    SupabaseQuery(RecordingBuilder(calls)).select("*").order("asking_price", descending=False).execute()

    assert call(calls, "order")[2]["desc"] is False


def test_writes_are_delegated_with_the_payload_positional() -> None:
    calls: list[tuple] = []
    SupabaseQuery(RecordingBuilder(calls)).insert({"title": "x"}).execute()
    assert call(calls, "insert")[1] == ({"title": "x"},)

    calls = []
    SupabaseQuery(RecordingBuilder(calls)).update({"status": "sold"}).eq("id", "l1").execute()
    assert names(calls) == ["update", "eq", "execute"]
    assert call(calls, "update")[1] == ({"status": "sold"},)

    calls = []
    SupabaseQuery(RecordingBuilder(calls)).upsert({"id": "p1"}, on_conflict="user_id,listing_id").execute()
    assert call(calls, "upsert")[2] == {"on_conflict": "user_id,listing_id"}

    calls = []
    SupabaseQuery(RecordingBuilder(calls)).upsert({"id": "p1"}).execute()
    assert "on_conflict" not in call(calls, "upsert")[2]


def test_update_then_delete_filters_apply_after_the_write_verb() -> None:
    calls: list[tuple] = []
    SupabaseQuery(RecordingBuilder(calls)).delete().eq("id", "l1").eq("seller_id", "s1").execute()

    assert names(calls) == ["delete", "eq", "eq", "execute"]


# ------------------------------------------------------------------ result mapping

def test_execute_normalises_rows_and_count() -> None:
    response = SimpleNamespace(data=[{"id": "1"}, {"id": "2"}], count=57)
    result = SupabaseQuery(RecordingBuilder([], response=response)).select("*", count="exact").execute()

    assert isinstance(result, QueryResult)
    assert len(result.rows) == 2
    assert result.count == 57
    assert result.first == {"id": "1"}


def test_execute_tolerates_a_null_payload() -> None:
    result = SupabaseQuery(RecordingBuilder([], response=SimpleNamespace(data=None, count=None))).select("*").execute()

    assert result.rows == []
    assert result.count is None
    assert result.first is None


def test_query_result_helpers() -> None:
    empty = QueryResult()
    assert len(empty) == 0
    assert list(empty) == []
    assert empty.first is None


# ------------------------------------------------- data-plane error translation

def test_constraint_violations_become_app_errors_not_raw_500s() -> None:
    """A duplicate accepted offer must surface as 409, not an unhandled exception."""
    builder = RecordingBuilder([], error=RuntimeError("duplicate key value violates unique schema offers_one_accepted_per_listing"))

    with pytest.raises(ConflictError) as exc:
        SupabaseQuery(builder, resource="offer").insert({"listing_id": "l1"}).execute()

    assert exc.value.status_code == 409
    assert "offer" in exc.value.message


def test_outages_become_502_with_a_readable_message() -> None:
    builder = RecordingBuilder([], error=RuntimeError("Failed to fetch"))

    with pytest.raises(ExternalServiceError) as exc:
        SupabaseQuery(builder, resource="listing").select("*").execute()

    assert exc.value.status_code == 502


def test_app_errors_from_the_builder_are_passed_through_unchanged() -> None:
    builder = RecordingBuilder([], error=NotFoundError("gone"))

    with pytest.raises(NotFoundError):
        SupabaseQuery(builder, resource="listing").select("*").execute()


# ------------------------------------------------------------------------ auth

def auth_client(response) -> SimpleNamespace:
    return SimpleNamespace(auth=SimpleNamespace(
        sign_up=lambda payload: response,
        sign_in_with_password=lambda payload: response,
    ))


def session_response(user_id="u1", email="a@b.com", access="tok", refresh="ref"):
    return SimpleNamespace(
        session=SimpleNamespace(access_token=access, refresh_token=refresh, user=None),
        user=SimpleNamespace(id=user_id, email=email),
    )


def test_sign_up_extracts_session_and_tokens() -> None:
    client = auth_client(session_response())
    session = SupabaseAuth(client).sign_up("a@b.com", "pw")

    assert session.user.id == "u1"
    assert session.user.email == "a@b.com"
    assert session.access_token == "tok"
    assert session.refresh_token == "ref"


def test_sign_in_falls_back_to_the_session_user_object() -> None:
    response = SimpleNamespace(
        session=SimpleNamespace(access_token="tok", refresh_token="ref", user=SimpleNamespace(id="u9", email="x@y.z")),
        user=None,
    )
    session = SupabaseAuth(auth_client(response)).sign_in("x@y.z", "pw")

    assert session.user.id == "u9"
    assert session.user.email == "x@y.z"


def test_email_confirmation_flow_raises_a_readable_auth_error() -> None:
    """Supabase returns a user but no session when confirmation is required."""
    response = SimpleNamespace(session=None, user=SimpleNamespace(id="u1", email="a@b.com"))

    with pytest.raises(AuthenticationError) as exc:
        SupabaseAuth(auth_client(response)).sign_up("a@b.com", "pw")

    assert "confirm your email" in exc.value.message


def test_missing_user_id_on_a_session_is_an_external_failure() -> None:
    response = SimpleNamespace(
        session=SimpleNamespace(access_token="tok", refresh_token="ref", user=None),
        user=SimpleNamespace(id="", email="a@b.com"),
    )

    with pytest.raises(ExternalServiceError):
        SupabaseAuth(auth_client(response)).sign_in("a@b.com", "pw")


def test_sign_out_swallows_upstream_failures() -> None:
    def boom() -> None:
        raise RuntimeError("network down")

    client = SimpleNamespace(auth=SimpleNamespace(sign_out=boom))
    SupabaseAuth(client).sign_out("tok")  # must not raise


def test_user_from_token_returns_none_for_a_missing_user() -> None:
    client = SimpleNamespace(auth=SimpleNamespace(get_user=lambda jwt: SimpleNamespace(user=None)))
    assert SupabaseAuth(client).user_from_token("tok") is None


def test_user_from_token_reads_the_verified_identity() -> None:
    client = SimpleNamespace(
        auth=SimpleNamespace(get_user=lambda jwt: SimpleNamespace(user=SimpleNamespace(id="u1", email="a@b.com")))
    )
    user = SupabaseAuth(client).user_from_token("tok")

    assert user is not None
    assert (user.id, user.email) == ("u1", "a@b.com")


# ----------------------------------------------------------- error translation

@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("duplicate key value violates unique constraint", ConflictError),
        ("the requested resource does not exist", NotFoundError),
        ("Invalid login credentials", AuthenticationError),
        ("User already registered", ConflictError),
        ("Password should be at least 6 characters", ValidationError),
        ("Failed to fetch", ExternalServiceError),
        ("connection timeout", ExternalServiceError),
    ],
)
def test_supabase_errors_translate_to_expected_status_codes(message: str, expected: type) -> None:
    translated = translate_supabase_error(RuntimeError(message), resource="listing")

    assert isinstance(translated, expected)
    assert translated.status_code == expected.status_code


def test_unknown_supabase_error_becomes_a_502_not_a_500() -> None:
    translated = translate_supabase_error(RuntimeError("surprising failure"), resource="listing")

    assert isinstance(translated, ExternalServiceError)
    assert translated.status_code == 502
    assert "surprising failure" in translated.message

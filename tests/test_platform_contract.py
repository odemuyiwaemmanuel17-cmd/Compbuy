"""AC-7 plus cross-cutting checks: dashboard content, session hygiene, schema contract."""

from __future__ import annotations

import re
import threading
from pathlib import Path

from app.db import QueryResult, run_query
from tests.conftest import VALID_LISTING, create_listing, make_client, register

MIGRATION = Path("supabase/migrations/0001_initial_schema.sql")
SEED = Path("supabase/seed.sql")

TABLES = ("profiles", "listings", "offers", "watchlist", "conversations", "messages")

ANON_PAGES = ["/", "/listings", "/listings?category=saas&min_price=1000", "/auth/login", "/auth/register"]
MEMBER_PAGES = [
    "/dashboard",
    "/seller/listings",
    "/seller/listings/new",
    "/buyer/offers",
    "/buyer/watchlist",
    "/messages",
]


def test_dashboard_summarises_listings_and_offers(app, seller, buyer) -> None:
    listing_id = create_listing(seller)
    buyer.post(
        f"/listings/{listing_id}/offers", data={"amount": "690000", "message": "Fast close."}, follow_redirects=False
    )

    page = seller.get("/dashboard")
    assert page.status_code == 200
    assert VALID_LISTING["title"] in page.text
    assert "$690,000" in page.text
    assert "Marco Silva" in page.text
    assert "Offers to review" in page.text

    buyer_page = buyer.get("/dashboard")
    assert "Offers you placed" in buyer_page.text
    assert "$690,000" in buyer_page.text


def test_anonymous_visitors_can_render_every_public_page(client) -> None:
    for path in ANON_PAGES:
        response = client.get(path)
        assert response.status_code == 200, path


def test_signed_in_members_can_render_every_member_page(app) -> None:
    member = register(app, "walker@compbuy.demo")
    for path in MEMBER_PAGES:
        response = member.get(path)
        assert response.status_code == 200, path


def test_missing_page_renders_the_404_template(client) -> None:
    response = client.get("/listings/not-a-real-uuid")
    assert response.status_code == 404
    assert "could not find" in response.text.lower()


def test_unknown_route_renders_the_404_template(client) -> None:
    response = client.get("/definitely-not-a-page")
    assert response.status_code == 404


def test_session_cookie_is_http_only_and_site_scoped(app) -> None:
    """AC-7: Supabase tokens travel in an httpOnly cookie, never readable by JS."""
    session = make_client(app)
    with session:
        response = session.post(
            "/auth/register",
            data={
                "email": "cookie@compbuy.demo",
                "password": "demo-password-123",
                "password_confirm": "demo-password-123",
                "display_name": "Cookie Tester",
            },
            follow_redirects=False,
        )
        cookie = response.headers["set-cookie"]

    assert "httponly" in cookie.lower()
    assert "samesite=lax" in cookie.lower()


def test_auth_tokens_are_never_rendered_into_html(app, seller, buyer, gateway) -> None:
    """AC-7: Supabase tokens stay in the signed cookie, out of the document."""
    listing_id = create_listing(seller)
    buyer.post(f"/listings/{listing_id}/offers", data={"amount": "500000"}, follow_redirects=False)

    secrets_in_play = set(gateway.auth.tokens)
    assert secrets_in_play, "expected issued tokens to inspect"

    for path in ("/dashboard", f"/listings/{listing_id}", "/buyer/offers", "/messages"):
        html = buyer.get(path).text
        for token in secrets_in_play:
            assert token not in html, path

    # The cookie value is signed and opaque, so the raw token must not appear in it.
    for cookie in buyer.cookies.jar:
        for token in secrets_in_play:
            assert token not in (cookie.value or "")


def test_html_output_is_escaped_against_script_injection(app, client, seller) -> None:
    payload = "<script>alert('xss')</script>"
    listing_id = create_listing(
        seller, title="Injection probe listing", one_liner=payload, description=payload + " padded to clear the minimum length requirement here."
    )

    page = client.get(f"/listings/{listing_id}")
    assert page.status_code == 200
    assert "<script>alert" not in page.text
    assert "&lt;script&gt;" in page.text


def test_migration_declares_every_table_with_row_level_security() -> None:
    """AC-7: RLS is defined for each marketplace table."""
    sql = MIGRATION.read_text(encoding="utf-8")

    for table in TABLES:
        assert f"create table if not exists public.{table}" in sql, table
        assert f"alter table public.{table} enable row level security;" in sql, table

    for table in TABLES:
        pattern = re.compile(rf'create policy "[^"]+" on public\.{table}\n', re.IGNORECASE)
        assert pattern.search(sql), f"{table} has no security policy"


def test_migration_constraints_mirror_the_python_validation() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "check (asking_price > 0)" in sql
    assert "check (annual_revenue >= 0)" in sql
    assert "check (amount > 0)" in sql
    assert "offers_buyer_is_not_seller check (buyer_id <> seller_id)" in sql
    assert "offers_one_accepted_per_listing" in sql
    assert "watchlist_unique_per_user unique (user_id, listing_id)" in sql
    assert "conversations_unique_thread unique (listing_id, buyer_id)" in sql


def test_seed_data_covers_public_and_private_states() -> None:
    sql = SEED.read_text(encoding="utf-8")

    assert "'published'" in sql
    assert "'draft'" in sql
    assert "auth.users" in sql
    assert "'pending'" in sql


def test_gateway_without_credentials_reports_clearly(monkeypatch) -> None:
    from app.config import Settings
    from app.db import SupabaseGateway
    from app.errors import ExternalServiceError

    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)

    try:
        SupabaseGateway(Settings(supabase_url=None, supabase_anon_key=None))
    except ExternalServiceError as exc:
        assert "SUPABASE_URL" in exc.message
    else:  # pragma: no cover - the constructor must fail
        raise AssertionError("SupabaseGateway should refuse to build without credentials")


def test_health_endpoint_reports_gateway_state(client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["gateway_configured"] is True
    assert body["supabase_configured"] is False


class _ThreadRecordingQuery:
    """Minimal ``Query`` that records which thread executed it."""

    def __init__(self) -> None:
        self.executed_on: int | None = None

    def select(self, columns: str = "*", *, count: str | None = None):
        return self

    def execute(self):
        self.executed_on = threading.get_ident()
        return QueryResult(rows=[{"id": "listing-1"}])


def test_blocking_supabase_calls_run_off_the_event_loop() -> None:
    """``supabase-py`` is synchronous, so services must not execute it on the loop."""
    import anyio

    query = _ThreadRecordingQuery()
    caller_thread = threading.get_ident()

    async def scenario():
        return await run_query(query)

    result = anyio.run(scenario)

    assert len(result.rows) == 1
    assert query.executed_on is not None
    assert query.executed_on != caller_thread, "gateway calls must be offloaded to a worker thread"

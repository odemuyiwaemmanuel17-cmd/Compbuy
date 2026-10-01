"""Shared pytest fixtures for the Compbuy suite."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import unconfigured_settings
from app.main import create_app
from tests.support.in_memory_gateway import InMemoryGateway

DEMO_PASSWORD = "demo-password-123"

VALID_LISTING = {
    "title": "Ledgerly bookkeeping SaaS",
    "business_name": "Ledgerly Software Unipessoal Lda.",
    "one_liner": "480 paying customers, 91% retention",
    "description": (
        "Bootstrap-built accounting tool for freelancers. Full codebase, domain, "
        "customer list, and twelve months of financials transfer with the sale."
    ),
    "reason_for_selling": (
        "I am relocating to Brazil and can no longer run a Portuguese company day to day."
    ),
    "category": "saas",
    "asking_price": "780000",
    "monthly_revenue": "20000",
    "net_profit": "8000",
    "currency": "USD",
    "country": "Portugal",
    "city": "Lisbon",
    "established_year": "2019",
}


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guarantee the suite passes with no Supabase credentials configured."""
    for variable in (
        "SUPABASE_URL",
        "SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SESSION_SECRET",
        "LISTINGS_PER_PAGE",
    ):
        monkeypatch.delenv(variable, raising=False)


@pytest.fixture
def gateway() -> Iterator[InMemoryGateway]:
    """In-memory gateway, installed for the duration of the test."""
    from app.database import set_gateway

    instance = InMemoryGateway()
    previous = set_gateway(instance)
    try:
        yield instance
    finally:
        set_gateway(previous)


@pytest.fixture
def app(gateway: InMemoryGateway):
    """App wired to the in-memory gateway.

    The gateway is installed by the ``gateway`` fixture rather than relying on
    app lifespan, because ``TestClient`` only runs startup/shutdown when used as
    a context manager and several tests hold more than one client open at once.
    """
    return create_app(settings=unconfigured_settings(), gateway=gateway)


@pytest.fixture
def paged_app(gateway: InMemoryGateway):
    """Same app but with a two-item catalogue page, for pagination tests."""
    settings = unconfigured_settings().with_overrides(listings_per_page=2)
    return create_app(settings=settings, gateway=gateway)


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    """Anonymous visitor with a fresh cookie jar."""
    with TestClient(app) as test_client:
        yield test_client


def make_client(app) -> TestClient:
    """A separate cookie jar bound to the same app (and therefore same gateway)."""
    return TestClient(app)


def register(app, email: str, *, display_name: str = "Marketplace User", password: str = DEMO_PASSWORD) -> TestClient:
    """Register and return a signed-in client for that account."""
    session = make_client(app)
    response = session.post(
        "/auth/register",
        data={
            "email": email,
            "password": password,
            "password_confirm": password,
            "display_name": display_name,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    assert session.get("/dashboard").status_code == 200
    return session


def create_listing(session: TestClient, *, publish: bool = True, **overrides: str) -> str:
    """Create a listing through the seller UI and return its id."""
    values = dict(VALID_LISTING)
    values.update({key: str(value) for key, value in overrides.items()})
    values["action"] = "publish" if publish else "draft"
    response = session.post("/listings/new", data=values, follow_redirects=False)
    assert response.status_code == 303, response.text
    location = response.headers["location"]
    # Redirect target is /seller/listings/{id}/edit
    parts = location.strip("/").split("/")
    return parts[2]


@pytest.fixture
def seller(app):
    return register(app, "seller@compbuy.demo", display_name="Priya Nair")


@pytest.fixture
def buyer(app):
    return register(app, "buyer@compbuy.demo", display_name="Marco Silva")

"""AC-3: authentication, sessions, and protected-route redirects."""

from __future__ import annotations

from tests.conftest import DEMO_PASSWORD, create_listing, make_client, register


def test_registration_creates_profile_and_signed_in_session(app, gateway) -> None:
    seller = register(app, "new-seller@compbuy.demo", display_name="Nadia Osei")

    response = seller.get("/seller/listings")
    assert response.status_code == 200
    assert "Nadia Osei" in response.text

    profiles = gateway.rows("profiles")
    assert len(profiles) == 1
    assert profiles[0]["email"] == "new-seller@compbuy.demo"
    assert profiles[0]["display_name"] == "Nadia Osei"


def test_registration_rejects_mismatched_passwords(app, gateway) -> None:
    session = make_client(app)
    with session:
        response = session.post(
            "/auth/register",
            data={
                "email": "mismatch@compbuy.demo",
                "password": DEMO_PASSWORD,
                "password_confirm": "entirely-other-1",
                "display_name": "Mismatch",
            },
            follow_redirects=False,
        )
        assert response.status_code == 422
        assert "Both passwords must match" in response.text
        assert gateway.rows("profiles") == []


def test_weak_password_is_rejected_before_reaching_supabase(app, gateway) -> None:
    session = make_client(app)
    with session:
        response = session.post(
            "/auth/register",
            data={
                "email": "weak@compbuy.demo",
                "password": "short",
                "password_confirm": "short",
                "display_name": "Weak",
            },
            follow_redirects=False,
        )
        assert response.status_code == 422
        assert gateway.rows("profiles") == []


def test_duplicate_email_registration_is_refused(app) -> None:
    register(app, "dupe@compbuy.demo")
    second = make_client(app)
    with second:
        response = second.post(
            "/auth/register",
            data={
                "email": "dupe@compbuy.demo",
                "password": DEMO_PASSWORD,
                "password_confirm": DEMO_PASSWORD,
                "display_name": "Dupe",
            },
            follow_redirects=False,
        )
        assert response.status_code == 422
        assert "already exists" in response.text


def test_sign_in_with_correct_credentials(client, app, gateway) -> None:
    register(app, "signin@compbuy.demo")

    response = client.post(
        "/auth/login",
        data={"email": "signin@compbuy.demo", "password": DEMO_PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert client.get("/dashboard").status_code == 200


def test_sign_in_with_wrong_password_shows_form_error(client, gateway) -> None:
    response = client.post(
        "/auth/login",
        data={"email": "nobody@compbuy.demo", "password": "wrong-password-1"},
        follow_redirects=False,
    )
    assert response.status_code == 422
    assert "Sign in" in response.text
    assert "incorrect" in response.text.lower() or "could not sign you in" in response.text.lower()
    assert client.get("/dashboard", follow_redirects=False).status_code == 303


def test_sign_in_redirects_to_the_original_target(client, app) -> None:
    register(app, "next@compbuy.demo")
    response = client.post(
        "/auth/login",
        data={
            "email": "next@compbuy.demo",
            "password": DEMO_PASSWORD,
            "next": "/buyer/watchlist",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/buyer/watchlist"


def test_unauthenticated_get_on_protected_page_redirects_to_login(client, gateway) -> None:
    """AC-3."""
    response = client.get("/seller/listings/new", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login?next=/seller/listings/new"
    assert "sign in" in client.get(response.headers["location"], follow_redirects=True).text.lower()


def test_unauthenticated_post_creates_nothing(client, gateway) -> None:
    """AC-3: the redirect must not execute the protected write."""
    response = client.post("/seller/listings/new", data={"title": "Sneaky listing"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/auth/login?next=")
    assert gateway.rows("listings") == []
    assert gateway.rows("offers") == []


def test_open_redirect_in_next_parameter_is_rejected(client, app) -> None:
    register(app, "safe@compbuy.demo")
    response = client.post(
        "/auth/login",
        data={
            "email": "safe@compbuy.demo",
            "password": DEMO_PASSWORD,
            "next": "https://evil.example.com/phish",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_logout_clears_the_session(app, gateway) -> None:
    seller = register(app, "bye@compbuy.demo")
    create_listing(seller)
    assert gateway.rows("listings")

    response = seller.post("/auth/logout", follow_redirects=False)
    assert response.status_code == 303

    assert seller.get("/dashboard", follow_redirects=False).status_code == 303
    assert seller.get("/seller/listings", follow_redirects=False).status_code == 303

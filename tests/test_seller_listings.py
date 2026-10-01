"""AC-1 and AC-4: seller listing creation, validation, and ownership."""

from __future__ import annotations

from tests.conftest import VALID_LISTING, create_listing


def test_seller_creates_published_listing_visible_to_everyone(app, client, seller, gateway) -> None:
    """AC-1."""
    listing_id = create_listing(seller, publish=True)

    row = next(item for item in gateway.rows("listings") if item["id"] == listing_id)
    assert row["status"] == "published"
    assert row["seller_id"] == gateway.rows("profiles")[0]["id"]

    detail = client.get(f"/listings/{listing_id}")
    assert detail.status_code == 200
    assert VALID_LISTING["title"] in detail.text

    browse = client.get("/listings", params={"category": "saas", "min_price": "100000"})
    assert browse.status_code == 200
    assert listing_id in browse.text


def test_draft_listing_is_hidden_from_public_pages(app, client, seller, gateway) -> None:
    listing_id = create_listing(seller, publish=False)

    assert gateway.rows("listings")[0]["status"] == "draft"
    assert client.get("/listings", params={"category": "saas"}).text.count(listing_id) == 0
    assert client.get(f"/listings/{listing_id}", follow_redirects=False).status_code == 404
    assert listing_id not in client.get("/").text


def test_seller_can_edit_own_listing(app, client, seller, gateway) -> None:
    listing_id = create_listing(seller)

    response = seller.post(
        f"/seller/listings/{listing_id}/edit",
        data={**VALID_LISTING, "title": "Renamed business for sale", "action": "draft_update"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    row = next(item for item in gateway.rows("listings") if item["id"] == listing_id)
    assert row["title"] == "Renamed business for sale"
    assert row["status"] == "published"


def test_publish_action_moves_a_draft_live(app, seller, gateway) -> None:
    listing_id = create_listing(seller, publish=False)

    response = seller.post(
        f"/seller/listings/{listing_id}/status", data={"status": "published"}, follow_redirects=False
    )
    assert response.status_code == 303

    row = next(item for item in gateway.rows("listings") if item["id"] == listing_id)
    assert row["status"] == "published"


def test_seller_deletes_own_listing(app, seller, gateway) -> None:
    listing_id = create_listing(seller)

    response = seller.post(f"/seller/listings/{listing_id}/delete", follow_redirects=False)
    assert response.status_code == 303
    assert gateway.rows("listings") == []


def test_blank_title_and_zero_price_are_rejected_with_no_row_written(app, seller, gateway) -> None:
    """AC-4."""
    response = seller.post(
        "/listings/new",
        data={**VALID_LISTING, "title": "", "asking_price": "0", "action": "publish"},
        follow_redirects=False,
    )

    assert response.status_code == 422
    assert gateway.rows("listings") == []
    assert "asking_price" in response.text
    assert "title" in response.text


def test_negative_revenue_is_rejected(app, seller, gateway) -> None:
    """AC-4: monthly_revenue must be a positive figure."""
    response = seller.post(
        "/listings/new",
        data={**VALID_LISTING, "monthly_revenue": "-500", "action": "publish"},
        follow_redirects=False,
    )

    assert response.status_code == 422
    assert "monthly_revenue" in response.text
    assert gateway.rows("listings") == []


def test_non_numeric_price_reports_a_field_error(app, seller, gateway) -> None:
    response = seller.post(
        "/listings/new",
        data={**VALID_LISTING, "asking_price": "lots", "action": "publish"},
        follow_redirects=False,
    )

    assert response.status_code == 422
    assert gateway.rows("listings") == []


def test_short_description_is_rejected(app, seller, gateway) -> None:
    response = seller.post(
        "/listings/new",
        data={**VALID_LISTING, "description": "too short", "action": "publish"},
        follow_redirects=False,
    )

    assert response.status_code == 422
    assert gateway.rows("listings") == []


def test_another_member_cannot_edit_or_delete_a_foreign_listing(app, seller, buyer, gateway) -> None:
    """AC-7: ownership is enforced in Python, not just by the form."""
    listing_id = create_listing(seller)

    edit_form = buyer.get(f"/seller/listings/{listing_id}/edit", follow_redirects=False)
    assert edit_form.status_code == 403

    update = buyer.post(
        f"/seller/listings/{listing_id}/edit",
        data={**VALID_LISTING, "title": "Hijacked listing title", "action": "draft_update"},
        follow_redirects=False,
    )
    assert update.status_code == 403

    delete = buyer.post(f"/seller/listings/{listing_id}/delete", follow_redirects=False)
    assert delete.status_code == 403

    row = next(item for item in gateway.rows("listings") if item["id"] == listing_id)
    assert row["title"] == VALID_LISTING["title"]
    assert row["status"] == "published"


def test_foreign_member_cannot_change_listing_status(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller, publish=False)

    response = buyer.post(
        f"/seller/listings/{listing_id}/status", data={"status": "published"}, follow_redirects=False
    )
    assert response.status_code == 403

    row = next(item for item in gateway.rows("listings") if item["id"] == listing_id)
    assert row["status"] == "draft"


def test_seller_workspace_lists_only_their_own_listings(app, seller, buyer, gateway) -> None:
    mine = create_listing(seller)
    theirs = create_listing(buyer, title="Another sellers business here")

    page = seller.get("/seller/listings")
    assert mine in page.text
    assert theirs not in page.text
    assert len(gateway.rows("listings")) == 2


def test_seller_form_round_trips_a_known_listing(app, seller) -> None:
    listing_id = create_listing(seller, net_profit="")

    page = seller.get(f"/seller/listings/{listing_id}/edit")
    assert page.status_code == 200
    assert VALID_LISTING["title"] in page.text
    assert 'value="2019"' in page.text
    assert 'value="20000"' in page.text

"""AC-5 and AC-6: the offer lifecycle and its guard rails."""

from __future__ import annotations

from tests.conftest import create_listing, register


def _place_offer(buyer, listing_id: str, amount: str = "700000", message: str = "Cash close in 45 days."):
    return buyer.post(
        f"/listings/{listing_id}/offers",
        data={"amount": amount, "message": message},
        follow_redirects=False,
    )


def _first_offer_id(gateway) -> str:
    offers = gateway.rows("offers")
    assert offers, "expected an offer row"
    return offers[0]["id"]


def test_buyer_offer_is_stored_and_seen_by_both_parties(app, client, seller, buyer, gateway) -> None:
    """AC-5."""
    listing_id = create_listing(seller)

    response = _place_offer(buyer, listing_id)
    assert response.status_code == 303

    row = gateway.rows("offers")[0]
    assert row["status"] == "pending"
    assert row["amount"] == 700000
    assert row["listing_id"] == listing_id

    assert row["id"] in seller.get("/dashboard").text
    assert "$700,000" in seller.get("/dashboard").text
    assert "Cash close in 45 days" in buyer.get("/buyer/offers").text

    browse = client.get(f"/listings/{listing_id}")
    assert browse.status_code == 200


def test_placing_an_offer_opens_a_two_party_thread(app, seller, buyer, gateway) -> None:
    """AC-5: the conversation exists with exactly both participants."""
    listing_id = create_listing(seller)
    _place_offer(buyer, listing_id)

    conversations = gateway.rows("conversations")
    assert len(conversations) == 1
    seller_id = gateway.rows("profiles")[0]["id"]
    buyer_id = gateway.rows("profiles")[1]["id"]
    assert {conversations[0]["buyer_id"], conversations[0]["seller_id"]} == {seller_id, buyer_id}
    assert conversations[0]["listing_id"] == listing_id


def test_seller_accepts_an_offer(app, seller, buyer, gateway) -> None:
    """AC-5 happy path."""
    listing_id = create_listing(seller)
    _place_offer(buyer, listing_id)
    offer_id = _first_offer_id(gateway)

    response = seller.post(f"/offers/{offer_id}/accept", follow_redirects=False)
    assert response.status_code == 303
    assert gateway.rows("offers")[0]["status"] == "accepted"
    assert "accepted" in seller.get("/dashboard").text.lower()


def test_second_acceptance_on_the_same_listing_conflicts(app, seller, buyer, gateway) -> None:
    """AC-5: only one acceptance may stand per listing."""
    listing_id = create_listing(seller)
    third = register(app, "third@compbuy.demo", display_name="Third Party")

    _place_offer(buyer, listing_id)
    first_offer = _first_offer_id(gateway)

    _place_offer(third, listing_id, amount="650000")
    second_offer = next(row["id"] for row in gateway.rows("offers") if row["id"] != first_offer)

    assert seller.post(f"/offers/{first_offer}/accept", follow_redirects=False).status_code == 303

    conflict = seller.post(f"/offers/{second_offer}/accept", follow_redirects=False)
    assert conflict.status_code == 409
    assert gateway.rows("offers")[1]["status"] == "pending"


def test_seller_declines_an_offer(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)
    _place_offer(buyer, listing_id)

    offer_id = _first_offer_id(gateway)
    assert seller.post(f"/offers/{offer_id}/decline", follow_redirects=False).status_code == 303
    assert gateway.rows("offers")[0]["status"] == "declined"


def test_declined_offer_cannot_be_accepted_afterwards(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)
    _place_offer(buyer, listing_id)
    offer_id = _first_offer_id(gateway)

    seller.post(f"/offers/{offer_id}/decline", follow_redirects=False)
    response = seller.post(f"/offers/{offer_id}/accept", follow_redirects=False)

    assert response.status_code == 409
    assert gateway.rows("offers")[0]["status"] == "declined"


def test_buyer_can_withdraw_a_pending_offer(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)
    _place_offer(buyer, listing_id)
    offer_id = _first_offer_id(gateway)

    assert buyer.post(f"/offers/{offer_id}/withdraw", follow_redirects=False).status_code == 303
    assert gateway.rows("offers")[0]["status"] == "withdrawn"


def test_seller_cannot_withdraw_a_buyers_offer(app, seller, buyer, gateway) -> None:
    """AC-7: the decision surface is bound to the right party."""
    listing_id = create_listing(seller)
    _place_offer(buyer, listing_id)

    response = seller.post(f"/offers/{_first_offer_id(gateway)}/withdraw", follow_redirects=False)
    assert response.status_code == 403
    assert gateway.rows("offers")[0]["status"] == "pending"


def test_a_stranger_cannot_accept_someone_elses_offer(app, seller, buyer, gateway) -> None:
    """AC-7."""
    listing_id = create_listing(seller)
    _place_offer(buyer, listing_id)
    stranger = register(app, "stranger@compbuy.demo")

    response = stranger.post(f"/offers/{_first_offer_id(gateway)}/accept", follow_redirects=False)
    assert response.status_code == 403
    assert gateway.rows("offers")[0]["status"] == "pending"


def test_seller_cannot_offer_on_their_own_listing(app, seller, gateway) -> None:
    """AC-6: 403 and no row written."""
    listing_id = create_listing(seller)

    response = _place_offer(seller, listing_id)
    assert response.status_code == 403
    assert gateway.rows("offers") == []
    assert gateway.rows("conversations") == []


def test_offering_on_an_unpublished_listing_is_not_found(app, buyer, seller, gateway) -> None:
    """AC-6: 404 for drafts, so they cannot be transacted on."""
    listing_id = create_listing(seller, publish=False)

    response = _place_offer(buyer, listing_id)
    assert response.status_code == 404
    assert gateway.rows("offers") == []


def test_offering_on_a_missing_listing_is_not_found(app, buyer, gateway) -> None:
    response = _place_offer(buyer, "00000000-0000-4000-8000-000000000000")
    assert response.status_code == 404
    assert gateway.rows("offers") == []


def test_zero_and_negative_amounts_are_rejected(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)

    for amount in ("0", "-250000", "not-a-number"):
        response = _place_offer(buyer, listing_id, amount=amount)
        assert response.status_code == 303
        page = buyer.get(f"/listings/{listing_id}").text
        assert "could not place that offer" in page

    assert gateway.rows("offers") == []


def test_offer_note_too_long_is_rejected(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)

    response = _place_offer(buyer, listing_id, message="x" * 2001)
    assert response.status_code == 303
    assert "could not place that offer" in buyer.get(f"/listings/{listing_id}").text
    assert gateway.rows("offers") == []


def test_detail_page_shows_the_buyers_own_offer_state(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)
    _place_offer(buyer, listing_id)

    page = buyer.get(f"/listings/{listing_id}")
    assert "Your last offer" in page.text
    assert "pending" in page.text

    other_page = seller.get(f"/listings/{listing_id}")
    assert "Your last offer" not in other_page.text

"""AC-5/AC-7: watchlist and negotiation threads."""

from __future__ import annotations

from tests.conftest import VALID_LISTING, create_listing, register


def _open_thread(buyer, listing_id: str) -> str:
    response = buyer.post(
        f"/listings/{listing_id}/offers",
        data={"amount": "640000", "message": "Keen to move quickly."},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return response


def test_watchlist_round_trip(app, client, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)

    saved = buyer.post(f"/buyer/watchlist/{listing_id}", follow_redirects=False)
    assert saved.status_code == 303
    assert len(gateway.rows("watchlist")) == 1

    page = buyer.get("/buyer/watchlist")
    assert listing_id in page.text
    assert VALID_LISTING["title"] in page.text

    removed = buyer.post(f"/buyer/watchlist/{listing_id}/remove", follow_redirects=False)
    assert removed.status_code == 303
    assert gateway.rows("watchlist") == []
    assert listing_id not in buyer.get("/buyer/watchlist").text


def test_saving_the_same_listing_twice_is_idempotent(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)

    buyer.post(f"/buyer/watchlist/{listing_id}", follow_redirects=False)
    buyer.post(f"/buyer/watchlist/{listing_id}", follow_redirects=False)

    assert len(gateway.rows("watchlist")) == 1
    assert "You have 1 listing" in buyer.get("/buyer/watchlist").text


def test_watchlist_is_private_to_its_owner(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)
    buyer.post(f"/buyer/watchlist/{listing_id}", follow_redirects=False)

    assert listing_id not in seller.get("/buyer/watchlist").text
    assert "Saved" not in seller.get(f"/listings/{listing_id}").text
    assert "Saved" in buyer.get(f"/listings/{listing_id}").text


def test_saving_an_unpublished_listing_is_refused(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller, publish=False)

    response = buyer.post(f"/buyer/watchlist/{listing_id}", follow_redirects=False)
    assert response.status_code == 404
    assert gateway.rows("watchlist") == []


def test_watchlist_drops_a_saved_listing_that_was_deleted(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)
    buyer.post(f"/buyer/watchlist/{listing_id}", follow_redirects=False)
    assert len(gateway.rows("watchlist")) == 1

    seller.post(f"/seller/listings/{listing_id}/delete", follow_redirects=False)

    buyer.get("/buyer/watchlist")
    assert gateway.rows("watchlist") == []


def test_thread_lists_messages_for_both_parties(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)
    _open_thread(buyer, listing_id)
    conversation_id = gateway.rows("conversations")[0]["id"]

    posted = buyer.post(
        f"/messages/{conversation_id}/reply", data={"body": "Happy to share financials under NDA."}, follow_redirects=False
    )
    assert posted.status_code == 303

    thread = buyer.get(f"/messages/{conversation_id}")
    assert "Happy to share financials under NDA." in thread.text
    assert "Marco Silva" in thread.text

    seller_thread = seller.get(f"/messages/{conversation_id}")
    assert "Happy to share financials under NDA." in seller_thread.text


def test_blank_message_is_rejected(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)
    _open_thread(buyer, listing_id)
    conversation_id = gateway.rows("conversations")[0]["id"]

    response = buyer.post(f"/messages/{conversation_id}/reply", data={"body": "   "}, follow_redirects=False)
    assert response.status_code == 303
    assert gateway.rows("messages") == []
    assert "Write a message before sending" in buyer.get(f"/messages/{conversation_id}").text


def test_an_outsider_cannot_read_or_write_a_thread(app, seller, buyer, gateway) -> None:
    """AC-7: participant-only access."""
    listing_id = create_listing(seller)
    _open_thread(buyer, listing_id)
    conversation_id = gateway.rows("conversations")[0]["id"]

    outsider = register(app, "outsider@compbuy.demo")

    assert outsider.get(f"/messages/{conversation_id}", follow_redirects=False).status_code == 403
    reply = outsider.post(
        f"/messages/{conversation_id}/reply", data={"body": "Let me in."}, follow_redirects=False
    )
    assert reply.status_code == 403
    assert gateway.rows("messages") == []


def test_conversation_list_only_shows_your_own_threads(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)
    _open_thread(buyer, listing_id)
    unrelated = register(app, "unrelated@compbuy.demo")

    threads = buyer.get("/messages")
    assert VALID_LISTING["title"] in threads.text
    assert unrelated.get("/messages").text.count("No conversations yet") == 1


def test_second_offer_reuses_the_same_thread(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)
    _open_thread(buyer, listing_id)
    _open_thread(buyer, listing_id)

    assert len(gateway.rows("conversations")) == 1
    assert len(gateway.rows("offers")) == 2

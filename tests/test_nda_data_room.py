"""Core Features 3 and 4: NDA-gated data room and the request/sign workflow.

The user-visible contract is: exact business name, monthly revenue, net profit,
annual revenue, margin and multiple stay hidden until the logged-in buyer holds a
*signed* NDA for that listing. Approval alone must not reveal anything.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import VALID_LISTING, create_listing

MONTHLY_REVENUE_DISPLAY = "$20,000"
NET_PROFIT_DISPLAY = "$8,000"
ANNUAL_REVENUE_DISPLAY = "$240,000"
LEGAL_NAME = VALID_LISTING["business_name"]
REASON = VALID_LISTING["reason_for_selling"]
ASKING_PRICE_DISPLAY = "$780,000"

REQUEST_NOTE = "Serious solo buyer, funds in place, can close in 30 days."


def _request_access(buyer: TestClient, listing_id: str, message: str = REQUEST_NOTE):
    return buyer.post(
        f"/listings/{listing_id}/nda-request", data={"message": message}, follow_redirects=False
    )


def _nda_id(gateway, index: int = 0) -> str:
    return gateway.rows("nda_requests")[index]["id"]


def _approve_to_signature(seller, buyer, listing_id, gateway) -> str:
    """Drive a request through pending -> approved -> signed and return its id."""
    assert _request_access(buyer, listing_id).status_code == 303
    nda_id = _nda_id(gateway)
    assert seller.post(f"/nda/{nda_id}/approve", follow_redirects=False).status_code == 303
    assert (
        buyer.post(f"/nda/{nda_id}/sign", data={"full_name": "Marco Silva"}, follow_redirects=False)
        .status_code
        == 303
    )
    return nda_id


# ------------------------------------------------------------------ the gate


def test_anonymous_visitor_sees_no_confidential_figure(app, client, seller) -> None:
    """Critical: the headline financials are absent without an NDA."""
    listing_id = create_listing(seller)

    page = client.get(f"/listings/{listing_id}")
    assert page.status_code == 200

    for secret in (
        MONTHLY_REVENUE_DISPLAY,
        NET_PROFIT_DISPLAY,
        ANNUAL_REVENUE_DISPLAY,
        LEGAL_NAME,
        REASON,
        "40%",
        "3.2x",
    ):
        assert secret not in page.text, secret

    # What *is* public still renders.
    assert ASKING_PRICE_DISPLAY in page.text
    assert VALID_LISTING["title"] in page.text
    assert "Under $250K / yr" in page.text
    assert "Members only" in page.text


def test_signed_in_buyer_without_nda_sees_no_confidential_figure(app, seller, buyer) -> None:
    listing_id = create_listing(seller)

    page = buyer.get(f"/listings/{listing_id}")
    assert page.status_code == 200
    assert MONTHLY_REVENUE_DISPLAY not in page.text
    assert LEGAL_NAME not in page.text
    assert "Members only" in page.text


def test_pending_request_does_not_unlock(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)
    assert _request_access(buyer, listing_id).status_code == 303

    page = buyer.get(f"/listings/{listing_id}")
    assert MONTHLY_REVENUE_DISPLAY not in page.text
    assert "Awaiting seller approval" in page.text


def test_approval_alone_does_not_unlock(app, seller, buyer, gateway) -> None:
    """Only a signature opens the data room, never approval by itself."""
    listing_id = create_listing(seller)
    assert _request_access(buyer, listing_id).status_code == 303
    nda_id = _nda_id(gateway)

    assert seller.post(f"/nda/{nda_id}/approve", follow_redirects=False).status_code == 303

    page = buyer.get(f"/listings/{listing_id}")
    assert MONTHLY_REVENUE_DISPLAY not in page.text
    assert "your signature needed" in page.text


def test_signed_nda_unlocks_every_confidential_field(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)
    _approve_to_signature(seller, buyer, listing_id, gateway)

    page = buyer.get(f"/listings/{listing_id}")
    assert page.status_code == 200
    assert MONTHLY_REVENUE_DISPLAY in page.text
    assert NET_PROFIT_DISPLAY in page.text
    assert ANNUAL_REVENUE_DISPLAY in page.text
    assert LEGAL_NAME in page.text
    assert REASON in page.text
    assert "3.2x" in page.text
    assert "40%" in page.text
    # A countersigned agreement is not withdrawable, so the page must not offer it.
    assert f"/nda/{_nda_id(gateway)}/withdraw" not in page.text


def test_other_members_stay_locked_after_one_buyer_signs(app, client, seller, buyer, gateway) -> None:
    """One buyer's signature must not open the room for anybody else."""
    from tests.conftest import register

    listing_id = create_listing(seller)
    _approve_to_signature(seller, buyer, listing_id, gateway)

    stranger = register(app, "stranger@compbuy.demo")
    for session in (client, stranger):
        page = session.get(f"/listings/{listing_id}")
        assert MONTHLY_REVENUE_DISPLAY not in page.text, page
        assert LEGAL_NAME not in page.text


def test_buyer_access_page_reuses_the_signature_to_show_figures(app, seller, buyer, gateway) -> None:
    """"Listings you can read in full" must not fall back to placeholders."""
    listing_id = create_listing(seller)
    _approve_to_signature(seller, buyer, listing_id, gateway)

    page = buyer.get("/buyer/access")
    assert page.status_code == 200
    assert LEGAL_NAME in page.text
    assert MONTHLY_REVENUE_DISPLAY in page.text
    assert "Data room open" in page.text


def test_seller_always_sees_their_own_data_room(app, seller) -> None:
    listing_id = create_listing(seller)

    page = seller.get(f"/listings/{listing_id}")
    assert MONTHLY_REVENUE_DISPLAY in page.text
    assert LEGAL_NAME in page.text

    workspace = seller.get("/seller/listings")
    assert "$240K" in workspace.text


# --------------------------------------------------------------- the workflow


def test_buyer_request_is_saved_with_both_parties(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)
    seller_id = gateway.rows("profiles")[0]["id"]
    buyer_id = gateway.raw("profiles")[1]["id"]

    response = _request_access(buyer, listing_id)
    assert response.status_code == 303

    row = gateway.rows("nda_requests")[0]
    assert row["listing_id"] == listing_id
    assert row["buyer_id"] == buyer_id
    assert row["seller_id"] == seller_id
    assert row["status"] == "pending"
    assert row["message"] == REQUEST_NOTE
    assert "Access requested" in buyer.get(f"/listings/{listing_id}").text


def test_seller_sees_the_request_on_their_surfaces(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)
    assert _request_access(buyer, listing_id).status_code == 303

    inbox = seller.get("/seller/data-room")
    assert inbox.status_code == 200
    assert VALID_LISTING["title"] in inbox.text
    assert REQUEST_NOTE in inbox.text
    assert "Marco Silva" in inbox.text
    assert "Awaiting your decision" in inbox.text

    dashboard = seller.get("/dashboard")
    assert "Data-room access requests" in dashboard.text
    assert REQUEST_NOTE in dashboard.text

    listing_page = seller.get(f"/listings/{listing_id}")
    assert listing_page.status_code == 200
    assert "This is your listing" in listing_page.text
    assert f"/seller/listings/{listing_id}/edit" in listing_page.text


def test_buyer_access_page_tracks_each_request(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)
    assert _request_access(buyer, listing_id).status_code == 303

    page = buyer.get("/buyer/access")
    assert page.status_code == 200
    assert VALID_LISTING["title"] in page.text
    assert "Awaiting seller approval" in page.text

    nda_id = _nda_id(gateway)
    seller.post(f"/nda/{nda_id}/approve", follow_redirects=False)
    assert "your signature needed" in buyer.get("/buyer/access").text


def test_seller_can_decline_and_the_buyer_can_ask_again(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)
    assert _request_access(buyer, listing_id).status_code == 303
    nda_id = _nda_id(gateway)

    assert seller.post(f"/nda/{nda_id}/decline", follow_redirects=False).status_code == 303
    assert gateway.rows("nda_requests")[0]["status"] == "rejected"
    assert "Declined" in buyer.get(f"/listings/{listing_id}").text

    assert _request_access(buyer, listing_id, message="Second ask, with a reference letter.").status_code == 303
    rows = gateway.rows("nda_requests")
    assert len(rows) == 1, "a declined pair reopens the same request rather than stacking"
    assert rows[0]["status"] == "pending"
    assert rows[0]["id"] == nda_id


def test_buyer_can_withdraw_a_pending_request(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)
    assert _request_access(buyer, listing_id).status_code == 303
    nda_id = _nda_id(gateway)

    assert buyer.post(f"/nda/{nda_id}/withdraw", follow_redirects=False).status_code == 303
    assert gateway.rows("nda_requests")[0]["status"] == "withdrawn"

    assert _request_access(buyer, listing_id).status_code == 303
    assert gateway.rows("nda_requests")[0]["status"] == "pending"


def test_signing_records_the_name_and_timestamp(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)
    assert _request_access(buyer, listing_id).status_code == 303
    nda_id = _nda_id(gateway)
    seller.post(f"/nda/{nda_id}/approve", follow_redirects=False)

    buyer.post(f"/nda/{nda_id}/sign", data={"full_name": "M. Silva", "kind": "loi"}, follow_redirects=False)
    row = gateway.rows("nda_requests")[0]
    assert row["status"] == "signed"
    assert row["signed_name"] == "M. Silva"
    assert row["signed_at"]

    assert "Signed as M. Silva" in buyer.get("/buyer/access").text


# ------------------------------------------------------------------- failures


def test_seller_inbox_offers_only_seller_actions(app, seller, buyer, gateway) -> None:
    """An approved request waits on the buyer, so the seller page must not offer to sign."""
    listing_id = create_listing(seller)
    assert _request_access(buyer, listing_id).status_code == 303
    nda_id = _nda_id(gateway)
    seller.post(f"/nda/{nda_id}/approve", follow_redirects=False)

    inbox = seller.get("/seller/data-room")
    assert f"/nda/{nda_id}/approve" not in inbox.text
    assert f"/nda/{nda_id}/decline" not in inbox.text
    assert f"/nda/{nda_id}/sign" not in inbox.text
    assert "Granted access" in inbox.text
    assert "Approved" in inbox.text


def test_free_text_on_every_new_surface_is_escaped(app, seller, buyer, gateway) -> None:
    """NDA notes, signer names, and confidential text all render through autoescape."""
    payload = "<script>alert('nda-xss')</script>"
    listing_id = create_listing(
        seller,
        title="Escape probe listing here",
        business_name=payload + " Ltd",
        reason_for_selling=payload + " and a long enough reason to satisfy validation.",
    )
    assert _request_access(buyer, listing_id, message=payload).status_code == 303

    for page in (
        buyer.get(f"/listings/{listing_id}"),
        seller.get(f"/listings/{listing_id}"),
        seller.get("/seller/data-room"),
        seller.get("/dashboard"),
        buyer.get("/buyer/access"),
    ):
        assert page.status_code == 200, page.text[:200]
        assert "<script>alert" not in page.text
    assert "&lt;script&gt;" in seller.get("/seller/data-room").text

    nda_id = _nda_id(gateway)
    seller.post(f"/nda/{nda_id}/approve", follow_redirects=False)
    buyer.post(f"/nda/{nda_id}/sign", data={"full_name": payload}, follow_redirects=False)

    signed = buyer.get("/buyer/access")
    assert "<script>alert" not in signed.text
    assert "&lt;script&gt;" in signed.text
    unlocked = buyer.get(f"/listings/{listing_id}")
    assert "<script>alert" not in unlocked.text
    assert payload not in unlocked.text
    assert gateway.rows("nda_requests")[0]["signed_name"] == payload


def test_seller_form_echoes_confidential_defaults_only_to_the_owner(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)

    own = seller.get(f"/seller/listings/{listing_id}/edit")
    assert own.status_code == 200
    assert LEGAL_NAME in own.text
    assert 'value="20000"' in own.text

    foreign = buyer.get(f"/seller/listings/{listing_id}/edit", follow_redirects=False)
    assert foreign.status_code == 403
    assert LEGAL_NAME not in foreign.text


def test_request_without_a_note_is_rejected(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)

    response = buyer.post(
        f"/listings/{listing_id}/nda-request", data={"message": "hi"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert "could not send that request" in buyer.get(f"/listings/{listing_id}").text
    assert gateway.rows("nda_requests") == []


def test_signing_without_a_name_is_rejected(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)
    _request_access(buyer, listing_id)
    nda_id = _nda_id(gateway)
    seller.post(f"/nda/{nda_id}/approve", follow_redirects=False)

    response = buyer.post(f"/nda/{nda_id}/sign", data={"full_name": "   "}, follow_redirects=False)
    assert response.status_code == 303
    assert "Signature missing" in buyer.get(f"/listings/{listing_id}").text
    assert gateway.rows("nda_requests")[0]["status"] == "approved"


def test_seller_cannot_request_access_to_their_own_listing(app, seller, gateway) -> None:
    listing_id = create_listing(seller)

    response = _request_access(seller, listing_id)
    assert response.status_code == 403
    assert gateway.rows("nda_requests") == []


def test_anonymous_visitor_cannot_request_access(app, client, seller, gateway) -> None:
    listing_id = create_listing(seller)

    response = _request_access(client, listing_id)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/auth/login")
    assert gateway.rows("nda_requests") == []


def test_duplicate_active_request_conflicts(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)
    assert _request_access(buyer, listing_id).status_code == 303

    second = _request_access(buyer, listing_id)
    assert second.status_code == 409
    assert len(gateway.rows("nda_requests")) == 1


def test_signed_in_member_cannot_sign_or_approve_a_foreign_request(app, seller, buyer, gateway) -> None:
    from tests.conftest import register

    listing_id = create_listing(seller)
    assert _request_access(buyer, listing_id).status_code == 303
    nda_id = _nda_id(gateway)

    stranger = register(app, "nosy@compbuy.demo")
    assert stranger.post(f"/nda/{nda_id}/approve", follow_redirects=False).status_code == 403
    assert stranger.post(f"/nda/{nda_id}/sign", data={"full_name": "Nosy Parker"}, follow_redirects=False).status_code == 403
    stranger_page = stranger.get("/seller/data-room")
    assert stranger_page.status_code == 200
    assert "No new requests" in stranger_page.text

    assert gateway.rows("nda_requests")[0]["status"] == "pending"


def test_buyer_cannot_approve_their_own_request(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)
    assert _request_access(buyer, listing_id).status_code == 303
    nda_id = _nda_id(gateway)

    assert buyer.post(f"/nda/{nda_id}/approve", follow_redirects=False).status_code == 403
    assert gateway.rows("nda_requests")[0]["status"] == "pending"


def test_seller_cannot_sign_as_the_buyer(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)
    assert _request_access(buyer, listing_id).status_code == 303
    nda_id = _nda_id(gateway)
    seller.post(f"/nda/{nda_id}/approve", follow_redirects=False)

    assert seller.post(f"/nda/{nda_id}/sign", data={"full_name": "Priya Nair"}, follow_redirects=False).status_code == 403
    assert gateway.rows("nda_requests")[0]["status"] == "approved"


def test_signing_before_approval_conflicts(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)
    assert _request_access(buyer, listing_id).status_code == 303
    nda_id = _nda_id(gateway)

    response = buyer.post(f"/nda/{nda_id}/sign", data={"full_name": "Marco Silva"}, follow_redirects=False)
    assert response.status_code == 409
    assert "still needs to approve" in response.text
    assert gateway.rows("nda_requests")[0]["status"] == "pending"


def test_approving_twice_is_a_conflict(app, seller, buyer, gateway) -> None:
    """The conditional update means one transition wins; the second cannot re-write it."""
    listing_id = create_listing(seller)
    assert _request_access(buyer, listing_id).status_code == 303
    nda_id = _nda_id(gateway)

    assert seller.post(f"/nda/{nda_id}/approve", follow_redirects=False).status_code == 303
    assert seller.post(f"/nda/{nda_id}/approve", follow_redirects=False).status_code == 409
    assert seller.post(f"/nda/{nda_id}/decline", follow_redirects=False).status_code == 409
    assert gateway.rows("nda_requests")[0]["status"] == "approved"


def test_requesting_an_unpublished_listing_is_not_found(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller, publish=False)

    assert _request_access(buyer, listing_id).status_code == 404
    assert gateway.rows("nda_requests") == []


def test_acting_on_a_missing_request_is_not_found(app, buyer, gateway) -> None:
    missing = "00000000-0000-4000-8000-000000000000"
    assert buyer.post(f"/nda/{missing}/sign", data={"full_name": "Marco Silva"}).status_code == 404
    assert buyer.post(f"/nda/{missing}/withdraw").status_code == 404


# ----------------------------------------------------------------------- LOI


def test_letter_of_intent_is_stored_and_labelled(app, seller, buyer, gateway) -> None:
    """Core Feature 5: an offer *or* a Letter of Intent on a listing."""
    listing_id = create_listing(seller)

    response = buyer.post(
        f"/listings/{listing_id}/offers",
        data={"amount": "700000", "message": "Indicative LOI, subject to diligence.", "kind": "loi"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    row = gateway.rows("offers")[0]
    assert row["kind"] == "loi"
    assert int(row["amount"]) == 700000

    inbox = seller.get("/dashboard")
    assert "Letter of intent" in inbox.text

    placed = buyer.get("/buyer/offers")
    assert "Letter of intent" in placed.text


def test_default_offer_kind_is_a_firm_offer(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)

    buyer.post(f"/listings/{listing_id}/offers", data={"amount": "700000"}, follow_redirects=False)
    assert gateway.rows("offers")[0]["kind"] == "offer"
    assert "Letter of intent" not in seller.get("/dashboard").text


def test_unknown_offer_kind_is_rejected(app, seller, buyer, gateway) -> None:
    listing_id = create_listing(seller)

    response = buyer.post(
        f"/listings/{listing_id}/offers",
        data={"amount": "700000", "kind": "guess"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "could not place that offer" in buyer.get(f"/listings/{listing_id}").text
    assert gateway.rows("offers") == []

"""Offer submission and seller decisions."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError as PydanticValidationError

from app.dependencies import CurrentUserDep, MessageServiceDep, OfferServiceDep
from app.models.user import User
from app.schemas.offer import OfferCreate
from app.session_store import flash
from app.utils.validation import field_errors

router = APIRouter(tags=["offers"])


def _listing_back(listing_id: str) -> RedirectResponse:
    return RedirectResponse(f"/listings/{listing_id}", status_code=303)


@router.post("/listings/{listing_id}/offers")
async def submit_offer(
    request: Request,
    listing_id: str,
    user: CurrentUserDep,
    offers: OfferServiceDep,
    messages: MessageServiceDep,
    amount: str = Form(""),
    message: str = Form(""),
):
    try:
        data = OfferCreate.model_validate({"amount": amount, "message": message})
    except PydanticValidationError as exc:
        errors = field_errors(exc)
        detail = "; ".join(next(iter(items)) for items in errors.values() if items) or "Enter a valid amount."
        flash(request, f"We could not place that offer: {detail}", category="error")
        return _listing_back(listing_id)

    # Missing (404), forbidden (403) and conflicting (409) outcomes propagate with
    # their own status rather than being hidden behind a redirect.
    offer, listing = await offers.submit(user.id, listing_id, data)

    # Open (or reuse) the negotiation thread so both parties can discuss terms.
    await messages.open_or_get(listing, user.id)

    flash(request, f"Offer of {offer.amount_display} sent to the seller.", category="success")
    return RedirectResponse("/buyer/offers", status_code=303)


@router.post("/offers/{offer_id}/accept")
async def accept_offer(
    request: Request,
    offer_id: str,
    user: CurrentUserDep,
    offers: OfferServiceDep,
):
    return await _decide(request, offer_id, user, offers, accept=True)


@router.post("/offers/{offer_id}/decline")
async def decline_offer(
    request: Request,
    offer_id: str,
    user: CurrentUserDep,
    offers: OfferServiceDep,
):
    return await _decide(request, offer_id, user, offers, accept=False)


async def _decide(
    request: Request, offer_id: str, user: User, offers: OfferServiceDep, *, accept: bool
) -> RedirectResponse:
    offer = await offers.decide(offer_id, user.id, accept=accept)
    verb = "accepted" if accept else "declined"
    flash(request, f"Offer from {offer.buyer_name or 'the buyer'} {verb}.", category="success")
    return RedirectResponse("/dashboard", status_code=303)


@router.post("/offers/{offer_id}/withdraw")
async def withdraw_offer(
    request: Request,
    offer_id: str,
    user: CurrentUserDep,
    offers: OfferServiceDep,
):
    await offers.withdraw(offer_id, user.id)
    flash(request, "Offer withdrawn.", category="success")
    return RedirectResponse("/buyer/offers", status_code=303)

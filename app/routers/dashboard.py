"""The signed-in member's workspace: listings, offers, and threads."""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, Request

from app.dependencies import (
    AuthServiceDep,
    CurrentUserDep,
    ListingServiceDep,
    MessageServiceDep,
    OfferServiceDep,
    SettingsDep,
)
from app.models.enums import OfferStatus
from app.models.offer import Offer
from app.rendering import render
from app.services.auth_service import AuthService

router = APIRouter(tags=["dashboard"])

UNKNOWN_BUYER_LABEL = "A buyer"


@router.get("/dashboard")
async def dashboard(
    request: Request,
    settings: SettingsDep,
    user: CurrentUserDep,
    listings: ListingServiceDep,
    offers: OfferServiceDep,
    messages: MessageServiceDep,
    auth: AuthServiceDep,
):
    my_listings = await listings.list_for_seller(user.id)
    inbound = await offers.for_seller(user.id)
    outbound = await offers.for_buyer(user.id)
    raw_threads = await messages.conversations_for(user.id)
    threads = await messages.attach_listing_titles(raw_threads)

    inbound_titles = {listing.id: listing.title for listing in my_listings}
    outbound_ids = sorted({offer.listing_id for offer in outbound if offer.listing_id})
    outbound_listings = await listings.published_by_ids(outbound_ids)
    outbound_titles = {listing.id: listing.title for listing in outbound_listings}

    inbound = _with_listing_titles(await _with_buyer_names(offers=inbound, auth=auth), inbound_titles)
    outbound = _with_listing_titles(outbound, outbound_titles)

    pending_count = sum(1 for offer in inbound if offer.status is OfferStatus.PENDING)
    published_count = sum(1 for listing in my_listings if listing.is_published)

    return render(
        request,
        "dashboard.html",
        {
            "settings": settings,
            "current_user": user,
            "my_listings": my_listings,
            "inbound_offers": inbound,
            "outbound_offers": outbound,
            "conversations": threads,
            "pending_count": pending_count,
            "published_count": published_count,
            "stats": [
                {"label": "Listings", "value": len(my_listings), "href": "/seller/listings"},
                {"label": "Published", "value": published_count, "href": "/seller/listings"},
                {"label": "Offers to review", "value": pending_count, "href": "/dashboard#offers-in"},
                {"label": "Offers placed", "value": len(outbound), "href": "/buyer/offers"},
                {"label": "Conversations", "value": len(threads), "href": "/messages"},
            ],
            "page_title": "Dashboard",
        },
    )


async def _with_buyer_names(*, offers: list[Offer], auth: AuthService) -> list[Offer]:
    buyer_ids = {offer.buyer_id for offer in offers if offer.buyer_id}
    if not buyer_ids:
        return offers
    profiles = await auth.load_users_by_id(buyer_ids)
    return [
        replace(
            offer,
            buyer_name=profiles[offer.buyer_id].name if offer.buyer_id in profiles else UNKNOWN_BUYER_LABEL,
        )
        for offer in offers
    ]


def _with_listing_titles(offers: list[Offer], titles: dict[str, str]) -> list[Offer]:
    return [replace(offer, listing_title=titles.get(offer.listing_id, "")) for offer in offers]

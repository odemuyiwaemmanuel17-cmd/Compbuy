"""The signed-in member's workspace: listings, offers, and threads."""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, Request

from app.dependencies import (
    AuthServiceDep,
    CurrentUserDep,
    ListingServiceDep,
    MessageServiceDep,
    NdaServiceDep,
    OfferServiceDep,
    SettingsDep,
)
from app.models.enums import NdaStatus, OfferStatus
from app.models.offer import Offer
from app.rendering import render
from app.routers.nda import attach_buyer_names, label_requests
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
    nda: NdaServiceDep,
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

    incoming_requests = await attach_buyer_names(
        label_requests(await nda.for_seller(user.id), inbound_titles), auth
    )
    buyer_requests = await nda.for_buyer(user.id)
    buyer_titles = await listings.titles_by_ids(
        sorted({item.listing_id for item in buyer_requests if item.listing_id})
    )
    my_requests = label_requests(buyer_requests, buyer_titles)

    inbound = _with_listing_titles(await _with_buyer_names(offers=inbound, auth=auth), inbound_titles)
    outbound = _with_listing_titles(outbound, outbound_titles)

    pending_offers = [offer for offer in inbound if offer.status is OfferStatus.PENDING]
    pending_requests = [item for item in incoming_requests if item.status is NdaStatus.PENDING]
    published_count = sum(1 for listing in my_listings if listing.is_published)

    return render(
        request,
        "dashboard.html",
        {
            "settings": settings,
            "current_user": user,
            "my_listings": my_listings,
            "inbound_offers": inbound,
            "pending_offers": pending_offers,
            "outbound_offers": outbound,
            "conversations": threads,
            "pending_count": len(pending_offers),
            "published_count": published_count,
            "pending_requests": pending_requests,
            "incoming_requests": incoming_requests,
            "my_requests": my_requests,
            "stats": [
                {"label": "Listings", "value": len(my_listings), "href": "/seller/listings"},
                {"label": "Published", "value": published_count, "href": "/seller/listings"},
                {"label": "Offers to review", "value": len(pending_offers), "href": "/dashboard#offers-in"},
                {"label": "Access requests", "value": len(pending_requests), "href": "/seller/data-room"},
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

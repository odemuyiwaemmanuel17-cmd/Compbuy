"""Buyer surfaces: watchlist and the offers the buyer has placed."""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.dependencies import (
    CurrentUserDep,
    ListingServiceDep,
    OfferServiceDep,
    SettingsDep,
    WatchlistServiceDep,
)
from app.models.offer import Offer
from app.rendering import render
from app.session_store import flash

router = APIRouter(prefix="/buyer", tags=["buyer"])

REMOVED_LISTING_LABEL = "Listing removed"


@router.get("/watchlist")
async def watchlist_page(
    request: Request,
    settings: SettingsDep,
    user: CurrentUserDep,
    watchlist: WatchlistServiceDep,
):
    saved = await watchlist.saved_listings(user.id)
    return render(
        request,
        "buyer/watchlist.html",
        {
            "settings": settings,
            "current_user": user,
            "listings": saved,
            "page_title": "Saved businesses",
        },
    )


@router.get("/offers")
async def my_offers(
    request: Request,
    settings: SettingsDep,
    user: CurrentUserDep,
    offers: OfferServiceDep,
    listings: ListingServiceDep,
):
    placed = await offers.for_buyer(user.id)
    titles = await _titles_for(placed, listings)
    decorated = [replace(offer, listing_title=titles.get(offer.listing_id, REMOVED_LISTING_LABEL)) for offer in placed]
    return render(
        request,
        "buyer/offers.html",
        {
            "settings": settings,
            "current_user": user,
            "offers": decorated,
            "page_title": "My offers",
        },
    )


async def _titles_for(placed: list[Offer], listings: ListingServiceDep) -> dict[str, str]:
    listing_ids = sorted({offer.listing_id for offer in placed if offer.listing_id})
    if not listing_ids:
        return {}
    resolved = await listings.published_by_ids(listing_ids)
    return {listing.id: listing.title for listing in resolved}


@router.post("/watchlist/{listing_id}")
async def save_listing(
    request: Request,
    listing_id: str,
    user: CurrentUserDep,
    watchlist: WatchlistServiceDep,
):
    count = await watchlist.add(user.id, listing_id)
    plural = "listing" if count == 1 else "listings"
    flash(request, f"Saved. You have {count} {plural} on your watchlist.", category="success")
    return RedirectResponse(f"/listings/{listing_id}", status_code=303)


@router.post("/watchlist/{listing_id}/remove")
async def remove_saved_listing(
    request: Request,
    listing_id: str,
    user: CurrentUserDep,
    watchlist: WatchlistServiceDep,
):
    await watchlist.remove(user.id, listing_id)
    flash(request, "Removed from your watchlist.", category="info")
    return RedirectResponse("/buyer/watchlist", status_code=303)

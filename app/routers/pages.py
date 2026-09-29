"""Public catalogue: home page, search results, and listing detail."""

from __future__ import annotations

import math

from fastapi import APIRouter, Request

from app.dependencies import (
    AuthServiceDep,
    ListingServiceDep,
    OfferServiceDep,
    OptionalUserDep,
    SettingsDep,
    WatchlistServiceDep,
)
from app.rendering import render
from app.schemas.listing import ListingFilters

FEATURED_LIMIT = 6

router = APIRouter(tags=["public"])


@router.get("/")
async def home(
    request: Request,
    settings: SettingsDep,
    listings: ListingServiceDep,
    user: OptionalUserDep,
):
    featured, published_count = await listings.newest_published(FEATURED_LIMIT)
    return render(
        request,
        "home.html",
        {
            "settings": settings,
            "current_user": user,
            "featured_listings": featured,
            "published_count": published_count,
            "page_title": "Buy and sell businesses",
        },
    )


@router.get("/listings")
async def catalogue(
    request: Request,
    settings: SettingsDep,
    listings: ListingServiceDep,
    watchlist: WatchlistServiceDep,
    user: OptionalUserDep,
):
    filters = ListingFilters.from_request(
        dict(request.query_params), per_page=settings.listings_per_page
    )
    results, total = await listings.search(filters)
    saved_ids = await watchlist.saved_listing_ids(user.id) if user else set()
    total_pages = max(1, math.ceil(total / filters.per_page))
    return render(
        request,
        "listings/list.html",
        {
            "settings": settings,
            "current_user": user,
            "filters": filters,
            "listings": results,
            "total": total,
            "total_pages": total_pages,
            "saved_ids": saved_ids,
            "page_title": "Businesses for sale",
        },
    )


@router.get("/listings/{listing_id}")
async def listing_detail(
    request: Request,
    settings: SettingsDep,
    listing_id: str,
    listings: ListingServiceDep,
    offers: OfferServiceDep,
    watchlist: WatchlistServiceDep,
    auth: AuthServiceDep,
    user: OptionalUserDep,
):
    listing = await listings.get_by_id(listing_id, published_only=True)
    seller = await auth.load_user(listing.seller_id)
    saved_ids = await watchlist.saved_listing_ids(user.id) if user else set()
    my_offer = await offers.find_latest_for_buyer(listing.id, user.id) if user else None
    accepted = await offers.find_accepted_for_listing(listing.id)
    return render(
        request,
        "listings/detail.html",
        {
            "settings": settings,
            "current_user": user,
            "listing": listing,
            "seller": seller,
            "is_saved": listing.id in saved_ids,
            "is_own_listing": bool(user and listing.editable_by(user.id)),
            "my_offer": my_offer,
            "accepted_offer": accepted,
            "page_title": listing.title,
        },
    )

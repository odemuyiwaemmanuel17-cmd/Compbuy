"""Home page. Catalogue and detail routes live in app/routers/listings.py."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.dependencies import ListingServiceDep, OptionalUserDep, SettingsDep
from app.rendering import render
from app.routers.listings import FEATURED_LIMIT

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

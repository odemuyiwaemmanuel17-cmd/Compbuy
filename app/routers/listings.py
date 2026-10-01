"""Marketplace listings: browse, gated detail, and the seller create form.

Field extraction for the listing form lives here and is shared by the seller
workspace router, so create and edit cannot drift apart.
"""

from __future__ import annotations

import math
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError as PydanticValidationError

from app.dependencies import (
    AuthServiceDep,
    CurrentUserDep,
    ListingServiceDep,
    NdaServiceDep,
    OfferServiceDep,
    OptionalUserDep,
    SettingsDep,
    WatchlistServiceDep,
)
from app.errors import AppError
from app.models.listing import Listing
from app.rendering import render, render_form_error
from app.schemas.listing import ListingCreate, ListingFilters
from app.session_store import flash
from app.utils.validation import field_errors

FEATURED_LIMIT = 6

TEXT_FIELDS = (
    "title", "business_name", "one_liner", "description", "reason_for_selling",
    "category", "country", "city", "currency",
)
NUMBER_FIELDS = ("asking_price", "monthly_revenue", "net_profit", "established_year")
FORM_FIELDS = TEXT_FIELDS + NUMBER_FIELDS

PUBLISH_ACTIONS = {"publish", "publish_update"}
KNOWN_ACTIONS = PUBLISH_ACTIONS | {"draft", "draft_update"}

LISTING_FORM_TEMPLATE = "seller/listing_form.html"

router = APIRouter(tags=["listings"])


# ------------------------------------------------------------- form utilities

async def read_listing_fields(request: Request) -> dict[str, str]:
    """Collect the listing form fields, dropping blanks and unknown keys."""
    submitted = await request.form()
    values: dict[str, str] = {}
    for key in FORM_FIELDS:
        raw = submitted.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            values[key] = text
    values["action"] = str(submitted.get("action") or "draft").strip()
    return values


def form_values(raw: dict[str, str]) -> dict[str, Any]:
    return {key: raw.get(key, "") for key in FORM_FIELDS}


def listing_form_values(listing: Listing) -> dict[str, Any]:
    """Pre-fill the edit form from stored monthly figures."""
    return {
        "title": listing.title,
        "business_name": listing.business_name,
        "one_liner": listing.one_liner,
        "description": listing.description,
        "reason_for_selling": listing.reason_for_selling,
        "category": listing.category,
        "asking_price": listing.asking_price,
        "monthly_revenue": listing.monthly_revenue if listing.monthly_revenue is not None else "",
        "net_profit": listing.net_profit if listing.net_profit is not None else "",
        "currency": listing.currency,
        "country": listing.country,
        "city": listing.city,
        "established_year": listing.established_year or "",
    }


# ------------------------------------------------------------------- browse

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


# -------------------------------------------------------------- create form
# Registered before /listings/{listing_id} so "new" is never read as an id.

@router.get("/listings/new")
async def new_listing_form(request: Request, settings: SettingsDep, user: CurrentUserDep):
    return render(
        request,
        LISTING_FORM_TEMPLATE,
        {
            "settings": settings,
            "current_user": user,
            "form": form_values({}),
            "editing": None,
            "page_title": "List a business",
        },
    )


@router.post("/listings/new")
async def create_listing(
    request: Request,
    settings: SettingsDep,
    user: CurrentUserDep,
    listings: ListingServiceDep,
):
    raw = await read_listing_fields(request)
    context = {
        "settings": settings,
        "current_user": user,
        "form": form_values(raw),
        "editing": None,
    }
    if raw["action"] not in KNOWN_ACTIONS:
        return render_form_error(
            request,
            LISTING_FORM_TEMPLATE,
            context,
            message="Choose either Save draft or Publish.",
            field_errors={"action": ["Unknown save action."]},
        )

    payload = {key: raw[key] for key in FORM_FIELDS if key in raw}
    try:
        data = ListingCreate.model_validate(payload)
    except PydanticValidationError as exc:
        return render_form_error(
            request,
            LISTING_FORM_TEMPLATE,
            context,
            message="Please correct the highlighted fields before saving.",
            field_errors=field_errors(exc),
        )

    try:
        created = await listings.create(
            user.id, data, publish=raw["action"] in PUBLISH_ACTIONS
        )
    except AppError as exc:
        return render_form_error(
            request,
            LISTING_FORM_TEMPLATE,
            context,
            message=exc.message,
            field_errors=exc.field_errors,
        )

    flash(
        request,
        "Your listing is live on the marketplace."
        if created.is_published
        else "Draft saved. Publish it when you are ready.",
        category="success",
    )
    return RedirectResponse(f"/seller/listings/{created.id}/edit", status_code=303)


@router.get("/listings/{listing_id}")
async def listing_detail(
    request: Request,
    settings: SettingsDep,
    listing_id: str,
    listings: ListingServiceDep,
    offers: OfferServiceDep,
    watchlist: WatchlistServiceDep,
    nda: NdaServiceDep,
    auth: AuthServiceDep,
    user: OptionalUserDep,
):
    """Public overview, with the data room revealed only to a signed buyer."""
    raw = await listings.get_by_id(listing_id, published_only=True)
    viewer_id = user.id if user else None
    nda_request = await nda.find_for_pair(raw.id, user.id) if user else None
    viewing = nda.reveal_with(raw, viewer_id, nda_request)
    seller = await auth.load_user(viewing.seller_id)
    saved_ids = await watchlist.saved_listing_ids(user.id) if user else set()
    my_offer = await offers.find_latest_for_buyer(viewing.id, user.id) if user else None
    accepted = await offers.find_accepted_for_listing(viewing.id)
    return render(
        request,
        "listings/detail.html",
        {
            "settings": settings,
            "current_user": user,
            "listing": viewing,
            "seller": seller,
            "is_saved": viewing.id in saved_ids,
            "is_own_listing": bool(user and viewing.editable_by(user.id)),
            "my_offer": my_offer,
            "accepted_offer": accepted,
            "nda_request": nda_request,
            "page_title": viewing.title,
        },
    )

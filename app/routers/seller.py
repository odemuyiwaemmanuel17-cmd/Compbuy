"""Seller workspace: review, edit, publish, and remove own listings.

Listing creation lives in app/routers/listings.py (per the module layout); this
router owns the management surface for listings the seller already has.
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError as PydanticValidationError

from app.dependencies import (
    CurrentUserDep,
    ListingServiceDep,
    NdaServiceDep,
    SettingsDep,
)
from app.errors import AppError
from app.models.enums import ListingStatus
from app.models.listing import Listing
from app.rendering import render, render_form_error
from app.routers.listings import (
    FORM_FIELDS,
    KNOWN_ACTIONS,
    PUBLISH_ACTIONS,
    form_values,
    listing_form_values,
    read_listing_fields,
)
from app.schemas.listing import ListingUpdate
from app.session_store import flash
from app.utils.validation import field_errors

router = APIRouter(prefix="/seller", tags=["seller"])

INDEX_TEMPLATE = "seller/listings.html"
FORM_TEMPLATE = "seller/listing_form.html"


@router.get("/listings")
async def my_listings(
    request: Request,
    settings: SettingsDep,
    user: CurrentUserDep,
    listings: ListingServiceDep,
    nda: NdaServiceDep,
):
    mine = await listings.list_for_seller(user.id)
    pending_requests = await nda.count_pending_for_seller(user.id)
    return render(
        request,
        INDEX_TEMPLATE,
        {
            "settings": settings,
            "current_user": user,
            "listings": mine,
            "published_count": sum(1 for item in mine if item.is_published),
            "pending_requests": pending_requests,
            "page_title": "My listings",
        },
    )


@router.get("/listings/{listing_id}/edit")
async def edit_listing_form(
    request: Request,
    settings: SettingsDep,
    listing_id: str,
    user: CurrentUserDep,
    listings: ListingServiceDep,
):
    listing = await listings.find_owned(listing_id, user.id)
    return render(
        request,
        FORM_TEMPLATE,
        {
            "settings": settings,
            "current_user": user,
            "form": listing_form_values(listing),
            "editing": listing,
            "page_title": "Edit listing",
        },
    )


@router.post("/listings/{listing_id}/edit")
async def update_listing(
    request: Request,
    settings: SettingsDep,
    listing_id: str,
    user: CurrentUserDep,
    listings: ListingServiceDep,
):
    raw = await read_listing_fields(request)
    existing = await listings.find_owned(listing_id, user.id)
    context = {
        "settings": settings,
        "current_user": user,
        "form": form_values(raw),
        "editing": existing,
    }
    if raw["action"] not in KNOWN_ACTIONS:
        return render_form_error(
            request,
            FORM_TEMPLATE,
            context,
            message="Choose either Save changes or Publish.",
            field_errors={"action": ["Unknown save action."]},
        )

    payload = {key: raw[key] for key in FORM_FIELDS if key in raw}
    payload["status"] = _status_from_action(raw["action"], existing)

    try:
        data = ListingUpdate.model_validate(payload)
    except PydanticValidationError as exc:
        return render_form_error(
            request,
            FORM_TEMPLATE,
            context,
            message="Please correct the highlighted fields before saving.",
            field_errors=field_errors(exc),
        )

    try:
        await listings.update(listing_id, user.id, data)
    except AppError as exc:
        return render_form_error(
            request,
            FORM_TEMPLATE,
            context,
            message=exc.message,
            field_errors=exc.field_errors,
        )

    flash(request, "Listing updated.", category="success")
    return RedirectResponse("/seller/listings", status_code=303)


def _status_from_action(action: str, existing: Listing) -> str:
    """Publish moves the listing live; saving changes preserves its current state."""
    if action in PUBLISH_ACTIONS:
        return ListingStatus.PUBLISHED.value
    return existing.status.value


@router.post("/listings/{listing_id}/status")
async def change_status(
    request: Request,
    settings: SettingsDep,
    listing_id: str,
    user: CurrentUserDep,
    listings: ListingServiceDep,
    status: str = Form(ListingStatus.DRAFT.value),
):
    try:
        target = ListingStatus(status)
    except ValueError:
        flash(request, "That listing status is not recognised.", category="error")
        return RedirectResponse("/seller/listings", status_code=303)

    updated = await listings.set_status(listing_id, user.id, target)
    flash(request, f"Listing marked as {updated.status.value}.", category="success")
    return RedirectResponse("/seller/listings", status_code=303)


@router.post("/listings/{listing_id}/delete")
async def delete_listing(
    request: Request,
    settings: SettingsDep,
    listing_id: str,
    user: CurrentUserDep,
    listings: ListingServiceDep,
):
    await listings.delete(listing_id, user.id)
    flash(request, "Listing deleted.", category="success")
    return RedirectResponse("/seller/listings", status_code=303)

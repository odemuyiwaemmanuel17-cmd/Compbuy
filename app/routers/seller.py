"""Seller workspace: create, edit, publish, and remove listings."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError as PydanticValidationError

from app.dependencies import CurrentUserDep, ListingServiceDep, SettingsDep
from app.errors import AppError
from app.models.enums import ListingStatus
from app.models.listing import Listing
from app.rendering import render, render_form_error
from app.schemas.listing import ListingCreate, ListingUpdate
from app.session_store import flash
from app.utils.validation import field_errors

router = APIRouter(prefix="/seller", tags=["seller"])

INDEX_TEMPLATE = "seller/listings.html"
FORM_TEMPLATE = "seller/listing_form.html"

TEXT_FIELDS = ("title", "one_liner", "description", "category", "country", "city", "currency")
NUMBER_FIELDS = ("asking_price", "annual_revenue", "annual_profit", "established_year")
FORM_FIELDS = TEXT_FIELDS + NUMBER_FIELDS

_PUBLISH_ACTIONS = {"publish", "publish_update"}
_KNOWN_ACTIONS = _PUBLISH_ACTIONS | {"draft", "draft_update"}


async def read_listing_fields(request: Request) -> dict[str, str]:
    """Collect the listing form fields, dropping blanks and unknown keys."""
    submitted = await request.form()
    values: dict[str, str] = {}
    for key in FORM_FIELDS:
        raw = submitted.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        if key in NUMBER_FIELDS and not _looks_numeric(text):
            # Keep the offending text so the template can show it back to the user.
            values[key] = text
            continue
        values[key] = text
    values["action"] = str(submitted.get("action") or "draft").strip()
    return values


def _looks_numeric(text: str) -> bool:
    try:
        float(text.replace(",", ""))
    except ValueError:
        return False
    return True


def _form_values(raw: dict[str, str]) -> dict[str, Any]:
    return {key: raw.get(key, "") for key in FORM_FIELDS}


def _listing_form_values(listing: Listing) -> dict[str, Any]:
    values: dict[str, Any] = {
        "title": listing.title,
        "one_liner": listing.one_liner,
        "description": listing.description,
        "category": listing.category,
        "asking_price": listing.asking_price,
        "annual_revenue": listing.annual_revenue,
        "currency": listing.currency,
        "country": listing.country,
        "city": listing.city,
    }
    values["annual_profit"] = listing.annual_profit if listing.annual_profit is not None else ""
    values["established_year"] = listing.established_year or ""
    return values


@router.get("/listings")
async def my_listings(
    request: Request,
    settings: SettingsDep,
    user: CurrentUserDep,
    listings: ListingServiceDep,
):
    mine = await listings.list_for_seller(user.id)
    return render(
        request,
        INDEX_TEMPLATE,
        {
            "settings": settings,
            "current_user": user,
            "listings": mine,
            "published_count": sum(1 for item in mine if item.is_published),
            "page_title": "My listings",
        },
    )


@router.get("/listings/new")
async def new_listing_form(
    request: Request, settings: SettingsDep, user: CurrentUserDep
):
    return render(
        request,
        FORM_TEMPLATE,
        {
            "settings": settings,
            "current_user": user,
            "form": _form_values({}),
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
        "form": _form_values(raw),
        "editing": None,
    }
    if raw["action"] not in _KNOWN_ACTIONS:
        return render_form_error(
            request,
            FORM_TEMPLATE,
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
            FORM_TEMPLATE,
            context,
            message="Please correct the highlighted fields before saving.",
            field_errors=field_errors(exc),
        )

    try:
        created = await listings.create(
            user.id, data, publish=raw["action"] in _PUBLISH_ACTIONS
        )
    except AppError as exc:
        return render_form_error(
            request,
            FORM_TEMPLATE,
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
            "form": _listing_form_values(listing),
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
        "form": _form_values(raw),
        "editing": existing,
    }
    if raw["action"] not in _KNOWN_ACTIONS:
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
    if action in _PUBLISH_ACTIONS:
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

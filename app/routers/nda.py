"""NDA request, approval, and signature workflow.

Access is granted only when a request reaches SIGNED, which requires the seller
to approve first and the buyer to countersign. Every decision route returns the
underlying status code (403/404/409) rather than hiding it behind a redirect.
"""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError as PydanticValidationError

from app.dependencies import (
    AuthServiceDep,
    CurrentUserDep,
    ListingServiceDep,
    NdaServiceDep,
    SettingsDep,
)
from app.models.nda import NdaRequest
from app.rendering import render
from app.schemas.nda import NdaRequestForm, NdaSignForm
from app.services.auth_service import AuthService
from app.session_store import flash
from app.utils.validation import field_errors

router = APIRouter(tags=["nda"])

SELLER_INBOX_TEMPLATE = "nda/seller_requests.html"
BUYER_REQUESTS_TEMPLATE = "nda/buyer_requests.html"


def _back_to_listing(listing_id: str) -> RedirectResponse:
    return RedirectResponse(f"/listings/{listing_id}", status_code=303)


# ------------------------------------------------------------------- requests

@router.post("/listings/{listing_id}/nda-request")
async def request_access(
    request: Request,
    listing_id: str,
    user: CurrentUserDep,
    nda: NdaServiceDep,
    message: str = Form(""),
):
    back = _back_to_listing(listing_id)
    try:
        data = NdaRequestForm.model_validate({"message": message})
    except PydanticValidationError as exc:
        errors = field_errors(exc)
        detail = "; ".join(
            first[0] for first in errors.values() if first
        ) or "add a short note explaining your interest"
        flash(request, f"We could not send that request — please {detail}.", category="error")
        return back

    created = await nda.request_access(user.id, listing_id, data)
    flash(
        request,
        "Access requested. The seller will be notified and can approve your data-room access.",
        category="success",
    )
    return _back_to_listing(created.listing_id)


@router.post("/nda/{nda_id}/sign")
async def sign_nda(
    request: Request,
    nda_id: str,
    user: CurrentUserDep,
    nda: NdaServiceDep,
    full_name: str = Form(""),
):
    existing = await nda.get_for_user(nda_id, user.id)
    back = _back_to_listing(existing.listing_id)
    try:
        data = NdaSignForm.model_validate({"full_name": full_name})
    except PydanticValidationError as exc:
        errors = field_errors(exc)
        detail = "; ".join(first[0] for first in errors.values() if first) or "type your full legal name"
        flash(request, f"Signature missing — {detail}.", category="error")
        return back

    signed = await nda.sign(nda_id, user.id, data.full_name)
    flash(request, "NDA signed. The full financial summary is now visible.", category="success")
    return _back_to_listing(signed.listing_id)


@router.post("/nda/{nda_id}/withdraw")
async def withdraw_request(
    request: Request,
    nda_id: str,
    user: CurrentUserDep,
    nda: NdaServiceDep,
):
    existing = await nda.get_for_user(nda_id, user.id)
    await nda.withdraw(nda_id, user.id)
    flash(request, "Access request withdrawn.", category="info")
    return _back_to_listing(existing.listing_id)


# ------------------------------------------------------------------ decisions

@router.post("/nda/{nda_id}/approve")
async def approve_request(
    request: Request,
    nda_id: str,
    user: CurrentUserDep,
    nda: NdaServiceDep,
):
    await nda.approve(nda_id, user.id)
    flash(request, "Access approved. The buyer can now sign to open the data room.", category="success")
    return RedirectResponse("/seller/data-room", status_code=303)


@router.post("/nda/{nda_id}/decline")
async def decline_request(
    request: Request,
    nda_id: str,
    user: CurrentUserDep,
    nda: NdaServiceDep,
):
    await nda.decline(nda_id, user.id)
    flash(request, "Access request declined.", category="info")
    return RedirectResponse("/seller/data-room", status_code=303)


# --------------------------------------------------------------------- pages

@router.get("/seller/data-room")
async def seller_data_room(
    request: Request,
    settings: SettingsDep,
    user: CurrentUserDep,
    nda: NdaServiceDep,
    listings: ListingServiceDep,
    auth: AuthServiceDep,
):
    """Everything buyers have asked for, grouped by status."""
    titles = {listing.id: listing.title for listing in await listings.list_for_seller(user.id)}
    requests_ = label_requests(await nda.for_seller(user.id), titles)
    requests_ = await attach_buyer_names(requests_, auth)
    pending = [item for item in requests_ if item.status.value == "pending"]
    granted = [item for item in requests_ if item.status.value in ("approved", "signed")]
    closed = [item for item in requests_ if item.status.value in ("rejected", "withdrawn")]
    return render(
        request,
        SELLER_INBOX_TEMPLATE,
        {
            "settings": settings,
            "current_user": user,
            "requests": requests_,
            "pending": pending,
            "granted": granted,
            "closed": closed,
            "page_title": "Data-room requests",
        },
    )


@router.get("/buyer/access")
async def buyer_access_requests(
    request: Request,
    settings: SettingsDep,
    user: CurrentUserDep,
    nda: NdaServiceDep,
    listings: ListingServiceDep,
):
    """Where the buyer stands on each listing they asked about."""
    requests_ = await nda.for_buyer(user.id)
    titles = await listings.titles_by_ids(sorted({item.listing_id for item in requests_ if item.listing_id}))
    requests_ = label_requests(requests_, titles)
    signed_ids = [item.listing_id for item in requests_ if item.unlocks_data_room]
    unlocked = [
        listing.unlocked_for(True) for listing in await listings.published_by_ids(signed_ids)
    ]
    return render(
        request,
        BUYER_REQUESTS_TEMPLATE,
        {
            "settings": settings,
            "current_user": user,
            "requests": requests_,
            "unlocked_listings": unlocked,
            "page_title": "My data-room access",
        },
    )


def label_requests(items: list[NdaRequest], titles: dict[str, str]) -> list[NdaRequest]:
    return [replace(item, listing_title=titles.get(item.listing_id, item.listing_title)) for item in items]


UNKNOWN_BUYER_LABEL = "A buyer"


async def attach_buyer_names(items: list[NdaRequest], auth: AuthService) -> list[NdaRequest]:
    buyer_ids = {item.buyer_id for item in items if item.buyer_id and not item.buyer_name}
    if not buyer_ids:
        return items
    profiles = await auth.load_users_by_id(buyer_ids)
    return [
        replace(
            item,
            buyer_name=item.buyer_name
            or (profiles[item.buyer_id].name if item.buyer_id in profiles else UNKNOWN_BUYER_LABEL),
        )
        for item in items
    ]

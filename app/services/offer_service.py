"""Offer submission and the seller's accept/decline decision."""

from __future__ import annotations

from app.db import run_query
from app.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.models.enums import OfferStatus
from app.models.listing import Listing
from app.models.offer import Offer
from app.schemas.offer import OfferCreate
from app.services.base import BaseService
from app.services.listing_service import ListingService

OFFER_COLUMNS = (
    "id, listing_id, buyer_id, seller_id, amount, message, status, currency, "
    "created_at, updated_at"
)


class OfferService(BaseService):
    def __init__(self, gateway=None) -> None:
        super().__init__(gateway)
        self._listings = ListingService(gateway)

    # ------------------------------------------------------------------ writes

    async def submit(self, buyer_id: str, listing_id: str, data: OfferCreate) -> tuple[Offer, Listing]:
        """Place a buyer's offer, after confirming it may legally exist."""
        listing = await self._listings.get_by_id(listing_id, published_only=True)
        if listing.seller_id == buyer_id:
            raise PermissionDeniedError("You cannot make an offer on your own listing.")
        if listing.status.value == "sold":
            raise ConflictError("This business has already been sold.")

        result = await run_query(
            self.gateway.table("offers").insert(
                data.to_values(
                    listing_id=listing.id,
                    buyer_id=buyer_id,
                    seller_id=listing.seller_id,
                    currency=listing.currency,
                )
            )
        )
        row = result.first
        if row is None:
            raise ConflictError("We could not record that offer. Please try again.")
        return Offer.from_row(row), listing

    async def decide(self, offer_id: str, seller_id: str, *, accept: bool) -> Offer:
        offer = await self.get_by_id(offer_id)
        if offer.seller_id != seller_id:
            raise PermissionDeniedError("Only the seller can respond to this offer.")
        if offer.is_decided:
            raise ConflictError(f"This offer was already {offer.status.value}.")
        if accept:
            await self._assert_no_other_acceptance(offer)

        new_status = OfferStatus.ACCEPTED if accept else OfferStatus.DECLINED
        result = await run_query(
            self.gateway.table("offers")
            .update({"status": new_status.value})
            .eq("id", offer.id)
            .eq("seller_id", seller_id)
            .eq("status", OfferStatus.PENDING.value)
        )
        row = result.first
        if row is None:
            raise ConflictError("This offer changed while you were deciding. Please refresh.")
        return Offer.from_row(row)

    async def withdraw(self, offer_id: str, buyer_id: str) -> Offer:
        offer = await self.get_by_id(offer_id)
        if offer.buyer_id != buyer_id:
            raise PermissionDeniedError("Only the buyer can withdraw their own offer.")
        if offer.is_decided:
            raise ConflictError(f"A {offer.status.value} offer can no longer be withdrawn.")
        result = await run_query(
            self.gateway.table("offers")
            .update({"status": OfferStatus.WITHDRAWN.value})
            .eq("id", offer.id)
            .eq("buyer_id", buyer_id)
            .eq("status", OfferStatus.PENDING.value)
        )
        row = result.first
        if row is None:
            raise ConflictError("This offer changed while you were updating it. Please refresh.")
        return Offer.from_row(row)

    async def _assert_no_other_acceptance(self, offer: Offer) -> None:
        result = await run_query(
            self.gateway.table("offers")
            .select(OFFER_COLUMNS)
            .eq("listing_id", offer.listing_id)
            .eq("status", OfferStatus.ACCEPTED.value)
            .neq("id", offer.id)
            .limit(1)
        )
        if result.first is not None:
            raise ConflictError("Another offer on this listing has already been accepted.")

    # ------------------------------------------------------------------- reads

    async def get_by_id(self, offer_id: str) -> Offer:
        result = await run_query(
            self.gateway.table("offers").select(OFFER_COLUMNS).eq("id", offer_id).limit(1)
        )
        row = result.first
        if row is None:
            raise NotFoundError("That offer no longer exists.")
        return Offer.from_row(row)

    async def get_for_user(self, offer_id: str, user_id: str) -> Offer:
        """Fetch an offer and confirm the requester participates in it."""
        offer = await self.get_by_id(offer_id)
        if not offer.is_for(user_id):
            raise PermissionDeniedError("You do not have access to this offer.")
        return offer

    async def for_seller(self, seller_id: str, *, status: OfferStatus | None = None) -> list[Offer]:
        query = (
            self.gateway.table("offers")
            .select(OFFER_COLUMNS)
            .eq("seller_id", seller_id)
            .order("created_at", descending=True)
        )
        if status is not None:
            query = query.eq("status", status.value)
        result = await run_query(query)
        return [Offer.from_row(row) for row in result.rows]

    async def for_buyer(self, buyer_id: str) -> list[Offer]:
        result = await run_query(
            self.gateway.table("offers")
            .select(OFFER_COLUMNS)
            .eq("buyer_id", buyer_id)
            .order("created_at", descending=True)
        )
        return [Offer.from_row(row) for row in result.rows]

    async def find_accepted_for_listing(self, listing_id: str) -> Offer | None:
        result = await run_query(
            self.gateway.table("offers")
            .select(OFFER_COLUMNS)
            .eq("listing_id", listing_id)
            .eq("status", OfferStatus.ACCEPTED.value)
            .limit(1)
        )
        row = result.first
        return Offer.from_row(row) if row else None

    async def find_latest_for_buyer(self, listing_id: str, buyer_id: str) -> Offer | None:
        """The buyer's most recent offer on this listing, for the detail page."""
        result = await run_query(
            self.gateway.table("offers")
            .select(OFFER_COLUMNS)
            .eq("listing_id", listing_id)
            .eq("buyer_id", buyer_id)
            .order("created_at", descending=True)
            .limit(1)
        )
        row = result.first
        return Offer.from_row(row) if row else None

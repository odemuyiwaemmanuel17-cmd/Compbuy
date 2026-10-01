"""NDA access requests and the data-room unlock decision.

State machine: pending -> approved -> signed unlocks the data room. A buyer may
also withdraw; a seller may decline. Every transition is written as a
conditional update (the expected prior status is part of the filter), so two
concurrent clicks cannot both take effect.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.database import run_query
from app.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.models.enums import NdaStatus
from app.models.listing import Listing
from app.models.nda import NdaRequest
from app.schemas.nda import NdaRequestForm
from app.services.base import BaseService
from app.services.listing_service import ListingService

NDA_COLUMNS = (
    "id, listing_id, buyer_id, seller_id, status, message, signed_name, "
    "created_at, updated_at, signed_at"
)


class NdaService(BaseService):
    def __init__(self, gateway=None) -> None:
        super().__init__(gateway)
        self._listings = ListingService(gateway)

    # ------------------------------------------------------------------ reads

    async def find_for_pair(self, listing_id: str, buyer_id: str) -> NdaRequest | None:
        result = await run_query(
            self.gateway.table("nda_requests")
            .select(NDA_COLUMNS)
            .eq("listing_id", listing_id)
            .eq("buyer_id", buyer_id)
            .limit(1)
        )
        row = result.first
        return NdaRequest.from_row(row) if row else None

    async def get_for_user(self, nda_id: str, user_id: str) -> NdaRequest:
        result = await run_query(
            self.gateway.table("nda_requests").select(NDA_COLUMNS).eq("id", nda_id).limit(1)
        )
        row = result.first
        if row is None:
            raise NotFoundError("That access request does not exist.")
        request = NdaRequest.from_row(row)
        if not request.is_for(user_id):
            raise PermissionDeniedError("You are not a party to this access request.")
        return request

    async def for_seller(self, seller_id: str, *, status: NdaStatus | None = None) -> list[NdaRequest]:
        query = (
            self.gateway.table("nda_requests")
            .select(NDA_COLUMNS)
            .eq("seller_id", seller_id)
            .order("created_at", descending=True)
        )
        if status is not None:
            query = query.eq("status", status.value)
        result = await run_query(query)
        return [NdaRequest.from_row(row) for row in result.rows]

    async def for_buyer(self, buyer_id: str) -> list[NdaRequest]:
        result = await run_query(
            self.gateway.table("nda_requests")
            .select(NDA_COLUMNS)
            .eq("buyer_id", buyer_id)
            .order("created_at", descending=True)
        )
        return [NdaRequest.from_row(row) for row in result.rows]

    async def count_pending_for_seller(self, seller_id: str) -> int:
        result = await run_query(
            self.gateway.table("nda_requests")
            .select(NDA_COLUMNS, count="exact")
            .eq("seller_id", seller_id)
            .eq("status", NdaStatus.PENDING.value)
            .limit(1)
        )
        if result.count is not None:
            return result.count
        return len(result.rows)

    @staticmethod
    def reveal_with(listing: Listing, viewer_id: str | None, request: NdaRequest | None) -> Listing:
        """The single data-room gate decision for a viewer.

        ``request`` is the viewer's own ``nda_requests`` row for this listing (load
        it with ``find_for_pair``), so callers that already display request status
        do not need a second query. The owner always sees their own data room;
        everybody else needs a *signed* agreement.
        """
        if viewer_id and listing.editable_by(viewer_id):
            return listing.unlocked_for(True)
        return listing.unlocked_for(bool(request and request.unlocks_data_room))

    # ----------------------------------------------------------------- writes

    async def request_access(
        self, buyer_id: str, listing_id: str, data: NdaRequestForm
    ) -> NdaRequest:
        listing = await self._listings.get_by_id(listing_id, published_only=True)
        if listing.editable_by(buyer_id):
            raise PermissionDeniedError("You already control this listing's data room.")

        existing = await self.find_for_pair(listing.id, buyer_id)
        if existing is not None:
            if existing.status.is_open or existing.unlocks_data_room:
                raise ConflictError(
                    f"You already have an active request for this listing ({existing.status_label})."
                )
            return await self._reopen(existing, data.message)

        result = await run_query(
            self.gateway.table("nda_requests").insert(
                data.to_values(
                    listing_id=listing.id, buyer_id=buyer_id, seller_id=listing.seller_id
                )
            )
        )
        row = result.first
        if row is None:
            raise ConflictError("We could not record that access request.")
        return NdaRequest.from_row(row)

    async def _reopen(self, existing: NdaRequest, message: str) -> NdaRequest:
        result = await run_query(
            self.gateway.table("nda_requests")
            .update({"status": NdaStatus.PENDING.value, "message": message, "signed_at": None, "signed_name": ""})
            .eq("id", existing.id)
            .eq("buyer_id", existing.buyer_id)
            .in_("status", [NdaStatus.REJECTED.value, NdaStatus.WITHDRAWN.value])
        )
        row = result.first
        if row is None:
            raise ConflictError("That request can no longer be reopened.")
        return NdaRequest.from_row(row)

    async def approve(self, nda_id: str, seller_id: str) -> NdaRequest:
        request = await self.get_for_seller(nda_id, seller_id)
        self._require_approvable(request, seller_id)
        return await self._transition(
            request,
            values={"status": NdaStatus.APPROVED.value},
            expected=NdaStatus.PENDING,
            actor_field="seller_id",
            actor_id=seller_id,
        )

    async def decline(self, nda_id: str, seller_id: str) -> NdaRequest:
        request = await self.get_for_seller(nda_id, seller_id)
        self._require_approvable(request, seller_id)
        return await self._transition(
            request,
            values={"status": NdaStatus.REJECTED.value},
            expected=NdaStatus.PENDING,
            actor_field="seller_id",
            actor_id=seller_id,
        )

    async def sign(self, nda_id: str, buyer_id: str, full_name: str) -> NdaRequest:
        request = await self.get_for_buyer(nda_id, buyer_id)
        if not request.signable_by(buyer_id):
            if request.status is NdaStatus.PENDING:
                raise ConflictError("The seller still needs to approve this request.")
            raise ConflictError(f"This request is already {request.status_label.lower()}.")
        return await self._transition(
            request,
            values={
                "status": NdaStatus.SIGNED.value,
                "signed_name": full_name,
                "signed_at": datetime.now(timezone.utc).isoformat(),
            },
            expected=NdaStatus.APPROVED,
            actor_field="buyer_id",
            actor_id=buyer_id,
        )

    async def withdraw(self, nda_id: str, buyer_id: str) -> NdaRequest:
        request = await self.get_for_buyer(nda_id, buyer_id)
        if not request.withdrawable_by(buyer_id):
            raise ConflictError(f"This request is already {request.status_label.lower()}.")
        # A buyer can back out at either open state, so guard on the status we read.
        return await self._transition(
            request,
            values={"status": NdaStatus.WITHDRAWN.value},
            expected=request.status,
            actor_field="buyer_id",
            actor_id=buyer_id,
        )

    # ------------------------------------------------------------- authorities

    async def get_for_seller(self, nda_id: str, seller_id: str) -> NdaRequest:
        """403 when the caller is not the listing's seller; state issues stay 409."""
        request = await self.get_for_user(nda_id, seller_id)
        if request.seller_id != seller_id:
            raise PermissionDeniedError("Only the seller can decide on this request.")
        return request

    async def get_for_buyer(self, nda_id: str, buyer_id: str) -> NdaRequest:
        request = await self.get_for_user(nda_id, buyer_id)
        if request.buyer_id != buyer_id:
            raise PermissionDeniedError("Only the requesting buyer can do that.")
        return request

    @staticmethod
    def _require_approvable(request: NdaRequest, seller_id: str) -> None:
        if not request.approvable_by(seller_id):
            raise ConflictError(f"This request is already {request.status_label.lower()}.")

    async def _transition(
        self,
        request: NdaRequest,
        *,
        values: dict[str, Any],
        expected: NdaStatus,
        actor_field: str,
        actor_id: str,
    ) -> NdaRequest:
        result = await run_query(
            self.gateway.table("nda_requests")
            .update(values)
            .eq("id", request.id)
            .eq(actor_field, actor_id)
            .eq("status", expected.value)
        )
        row = result.first
        if row is None:
            raise ConflictError("This request changed while you were acting on it. Please refresh.")
        return NdaRequest.from_row(row)

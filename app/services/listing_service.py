"""Listing reads, catalogue search, and seller-owned writes.

The gateway is reached with elevated credentials, so every mutation re-checks
ownership by ``seller_id`` here before touching the row.
"""

from __future__ import annotations

from app.database import Query, run_query
from app.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.models.enums import ListingStatus
from app.models.listing import Listing
from app.schemas.listing import ListingCreate, ListingFilters, ListingUpdate
from app.services.base import BaseService
from app.utils.parsing import as_str

LISTING_COLUMNS = (
    "id, seller_id, title, business_name, one_liner, description, reason_for_selling, "
    "category, asking_price, monthly_revenue, net_profit, annual_revenue, annual_profit, "
    "revenue_band, currency, country, city, established_year, status, image_urls, "
    "created_at, updated_at"
)

_SORT_COLUMNS: dict[str, tuple[str, bool]] = {
    "newest": ("created_at", True),
    "price_asc": ("asking_price", False),
    "price_desc": ("asking_price", True),
    "revenue_desc": ("annual_revenue", True),
}


class ListingService(BaseService):
    # ------------------------------------------------------------------ reads

    async def get_by_id(self, listing_id: str, *, published_only: bool = False) -> Listing:
        result = await run_query(
            self.gateway.table("listings")
            .select(LISTING_COLUMNS)
            .eq("id", listing_id)
            .limit(1)
        )
        row = result.first
        if row is None:
            raise NotFoundError("That listing is no longer on the marketplace.")
        listing = Listing.from_row(row)
        if published_only and not listing.is_published:
            raise NotFoundError("That listing is no longer on the marketplace.")
        return listing

    async def find_owned(self, listing_id: str, user_id: str) -> Listing:
        """Load a listing and confirm it belongs to ``user_id``."""
        listing = await self.get_by_id(listing_id)
        if not listing.editable_by(user_id):
            raise PermissionDeniedError("You can only manage your own listings.")
        return listing.unlocked_for(True)

    async def search(self, filters: ListingFilters) -> tuple[list[Listing], int]:
        query = self.gateway.table("listings").select(LISTING_COLUMNS, count="exact")
        query = apply_filters(query, filters)
        column, descending = _SORT_COLUMNS.get(filters.sort, ("created_at", True))
        start = (filters.page - 1) * filters.per_page
        query = query.order(column, descending=descending).range(start, start + filters.per_page - 1)
        result = await run_query(query)
        return [Listing.from_row(row) for row in result.rows], result.count or len(result.rows)

    async def list_for_seller(self, seller_id: str) -> list[Listing]:
        result = await run_query(
            self.gateway.table("listings")
            .select(LISTING_COLUMNS)
            .eq("seller_id", seller_id)
            .order("created_at", descending=True)
        )
        # Every row here belongs to the seller, so the data room is always open.
        return [Listing.from_row(row).unlocked_for(True) for row in result.rows]

    async def titles_by_ids(self, listing_ids: list[str]) -> dict[str, str]:
        """Headline titles for labelling related records; unpublished included."""
        if not listing_ids:
            return {}
        result = await run_query(
            self.gateway.table("listings").select("id, title").in_("id", listing_ids)
        )
        return {str(row["id"]): as_str(row.get("title")) for row in result.rows if row.get("id")}

    async def published_by_ids(self, listing_ids: list[str]) -> list[Listing]:
        """Featured listings for the home page, preserving the requested order."""
        if not listing_ids:
            return []
        result = await run_query(
            self.gateway.table("listings")
            .select(LISTING_COLUMNS)
            .in_("id", listing_ids)
            .eq("status", ListingStatus.PUBLISHED.value)
        )
        by_id = {row["id"]: Listing.from_row(row) for row in result.rows}
        return [by_id[list_id] for list_id in listing_ids if list_id in by_id]

    async def newest_published(self, limit: int) -> tuple[list[Listing], int]:
        result = await run_query(
            self.gateway.table("listings")
            .select(LISTING_COLUMNS, count="exact")
            .eq("status", ListingStatus.PUBLISHED.value)
            .order("created_at", descending=True)
            .limit(limit)
        )
        return [Listing.from_row(row) for row in result.rows], result.count or len(result.rows)

    # ---------------------------------------------------------------- writes

    async def create(self, seller_id: str, data: ListingCreate, *, publish: bool) -> Listing:
        status = ListingStatus.PUBLISHED if publish else ListingStatus.DRAFT
        result = await run_query(
            self.gateway.table("listings").insert(data.to_values(seller_id=seller_id, status=status))
        )
        row = result.first
        if row is None:
            raise ConflictError("We could not save that listing. Please try again.")
        return Listing.from_row(row)

    async def update(self, listing_id: str, user_id: str, data: ListingUpdate) -> Listing:
        existing = await self.find_owned(listing_id, user_id)
        result = await run_query(
            self.gateway.table("listings")
            .update(data.to_values(seller_id=user_id))
            .eq("id", existing.id)
            .eq("seller_id", user_id)
        )
        row = result.first
        if row is None:
            raise NotFoundError("That listing is no longer on the marketplace.")
        return Listing.from_row(row)

    async def set_status(self, listing_id: str, user_id: str, status: ListingStatus) -> Listing:
        existing = await self.find_owned(listing_id, user_id)
        if existing.status is status:
            return existing
        result = await run_query(
            self.gateway.table("listings")
            .update({"status": status.value})
            .eq("id", existing.id)
            .eq("seller_id", user_id)
        )
        row = result.first
        if row is None:
            raise NotFoundError("That listing is no longer on the marketplace.")
        return Listing.from_row(row)

    async def delete(self, listing_id: str, user_id: str) -> Listing:
        """Remove a listing after confirming ownership."""
        existing = await self.find_owned(listing_id, user_id)
        await run_query(
            self.gateway.table("listings").delete().eq("id", existing.id).eq("seller_id", user_id)
        )
        return existing


def apply_filters(query: Query, filters: ListingFilters) -> Query:
    """Translate catalogue filters into Supabase predicates."""
    query = query.eq("status", ListingStatus.PUBLISHED.value)
    if filters.q:
        pattern = f"%{filters.q}%"
        query = query.or_ilike(("title", "one_liner", "description"), pattern)
    if filters.category:
        query = query.eq("category", filters.category)
    if filters.min_price is not None:
        query = query.gte("asking_price", filters.min_price)
    if filters.max_price is not None:
        query = query.lte("asking_price", filters.max_price)
    if filters.min_band:
        query = query.in_("revenue_band", filters.band_floor_values)
    return query

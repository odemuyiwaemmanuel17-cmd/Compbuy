"""Buyer watchlist (saved listings)."""

from __future__ import annotations

from app.database import run_query
from app.services.base import BaseService
from app.services.listing_service import ListingService

WATCHLIST_COLUMNS = "id, user_id, listing_id, created_at"


class WatchlistService(BaseService):
    def __init__(self, gateway=None) -> None:
        super().__init__(gateway)
        self._listings = ListingService(gateway)

    async def add(self, user_id: str, listing_id: str) -> int:
        """Save a listing for later; idempotent per (user, listing)."""
        listing = await self._listings.get_by_id(listing_id, published_only=True)
        await run_query(
            self.gateway.table("watchlist").upsert(
                {"user_id": user_id, "listing_id": listing.id},
                on_conflict="user_id,listing_id",
            )
        )
        return await self.count(user_id)

    async def remove(self, user_id: str, listing_id: str) -> int:
        await run_query(
            self.gateway.table("watchlist")
            .delete()
            .eq("user_id", user_id)
            .eq("listing_id", listing_id)
        )
        return await self.count(user_id)

    async def saved_listing_ids(self, user_id: str) -> set[str]:
        result = await run_query(
            self.gateway.table("watchlist").select(WATCHLIST_COLUMNS).eq("user_id", user_id)
        )
        return {str(row["listing_id"]) for row in result.rows if row.get("listing_id")}

    async def count(self, user_id: str) -> int:
        result = await run_query(
            self.gateway.table("watchlist")
            .select(WATCHLIST_COLUMNS, count="exact")
            .eq("user_id", user_id)
            .limit(1)
        )
        if result.count is not None:
            return result.count
        return len(result.rows)

    async def saved_listings(self, user_id: str) -> list:
        """Watchlisted listings still on the marketplace, newest save first."""
        result = await run_query(
            self.gateway.table("watchlist")
            .select(WATCHLIST_COLUMNS)
            .eq("user_id", user_id)
            .order("created_at", descending=True)
        )
        ordered_ids = [str(row["listing_id"]) for row in result.rows if row.get("listing_id")]
        listings = await self._listings.published_by_ids(ordered_ids)
        if len(listings) != len(ordered_ids):
            # Saved rows pointing at deleted listings are no longer displayable.
            stale = {listing.id for listing in listings}
            for stale_id in ordered_ids:
                if stale_id not in stale:
                    await run_query(
                        self.gateway.table("watchlist")
                        .delete()
                        .eq("user_id", user_id)
                        .eq("listing_id", stale_id)
                    )
        return listings

"""A buyer's offer on a listing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.models.enums import OfferStatus
from app.utils.formatting import format_money, time_ago
from app.utils.parsing import as_datetime, as_str


@dataclass(frozen=True)
class Offer:
    id: str
    listing_id: str
    buyer_id: str
    seller_id: str
    amount: int
    message: str = ""
    status: OfferStatus = OfferStatus.PENDING
    currency: str = "USD"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Joined context for dashboards.
    listing_title: str = ""
    buyer_name: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Offer":
        listing_join = row.get("listing") if isinstance(row.get("listing"), dict) else {}
        buyer_join = row.get("buyer") if isinstance(row.get("buyer"), dict) else {}
        return cls(
            id=as_str(row.get("id")),
            listing_id=as_str(row.get("listing_id")),
            buyer_id=as_str(row.get("buyer_id")),
            seller_id=as_str(row.get("seller_id")),
            amount=int(row.get("amount") or 0),
            message=as_str(row.get("message")),
            status=cls._parse_status(row.get("status")),
            currency=as_str(row.get("currency"), default="USD").upper(),
            created_at=as_datetime(row.get("created_at")),
            updated_at=as_datetime(row.get("updated_at")) if row.get("updated_at") else None,
            listing_title=as_str(listing_join.get("title")) or as_str(row.get("listing_title")),
            buyer_name=as_str(buyer_join.get("display_name")) or as_str(row.get("buyer_name")),
        )

    @staticmethod
    def _parse_status(raw: Any) -> OfferStatus:
        try:
            return OfferStatus(as_str(raw, default="pending"))
        except ValueError:
            return OfferStatus.PENDING

    @property
    def amount_display(self) -> str:
        return format_money(self.amount, currency=self.currency)

    @property
    def is_decided(self) -> bool:
        return self.status.is_terminal

    @property
    def placed_ago(self) -> str:
        return time_ago(self.created_at)

    def is_for(self, user_id: str | None) -> bool:
        return bool(user_id) and user_id in {self.buyer_id, self.seller_id}

    def decidable_by(self, user_id: str | None) -> bool:
        return bool(user_id) and self.seller_id == user_id and not self.is_decided

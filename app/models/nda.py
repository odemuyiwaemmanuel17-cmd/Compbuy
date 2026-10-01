"""NDA access requests guarding a listing's data room."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.models.enums import NdaStatus
from app.utils.formatting import time_ago
from app.utils.parsing import as_datetime, as_str


@dataclass(frozen=True)
class NdaRequest:
    id: str
    listing_id: str
    buyer_id: str
    seller_id: str
    status: NdaStatus = NdaStatus.PENDING
    message: str = ""
    signed_name: str = ""
    created_at: datetime | None = None
    signed_at: datetime | None = None
    # Joined context.
    listing_title: str = ""
    buyer_name: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> NdaRequest:
        listing = row.get("listing") if isinstance(row.get("listing"), dict) else {}
        buyer = row.get("buyer") if isinstance(row.get("buyer"), dict) else {}
        return cls(
            id=as_str(row.get("id")),
            listing_id=as_str(row.get("listing_id")),
            buyer_id=as_str(row.get("buyer_id")),
            seller_id=as_str(row.get("seller_id")),
            status=cls._parse_status(row.get("status")),
            message=as_str(row.get("message")),
            signed_name=as_str(row.get("signed_name")),
            created_at=as_datetime(row.get("created_at")),
            signed_at=as_datetime(row["signed_at"]) if row.get("signed_at") else None,
            listing_title=as_str(listing.get("title")) or as_str(row.get("listing_title")),
            buyer_name=as_str(buyer.get("display_name")) or as_str(row.get("buyer_name")),
        )

    @staticmethod
    def _parse_status(raw: Any) -> NdaStatus:
        try:
            return NdaStatus(as_str(raw, default="pending"))
        except ValueError:
            return NdaStatus.PENDING

    @property
    def unlocks_data_room(self) -> bool:
        return self.status.unlocks_data_room

    @property
    def status_label(self) -> str:
        return self.status.label

    @property
    def requested_ago(self) -> str:
        return time_ago(self.created_at)

    @property
    def signed_ago(self) -> str:
        return time_ago(self.signed_at) if self.signed_at else ""

    def is_for(self, user_id: str | None) -> bool:
        return bool(user_id) and user_id in {self.buyer_id, self.seller_id}

    def approvable_by(self, user_id: str | None) -> bool:
        return bool(user_id) and user_id == self.seller_id and self.status is NdaStatus.PENDING

    def signable_by(self, user_id: str | None) -> bool:
        return bool(user_id) and user_id == self.buyer_id and self.status is NdaStatus.APPROVED

    def withdrawable_by(self, user_id: str | None) -> bool:
        return bool(user_id) and user_id == self.buyer_id and self.status.is_open

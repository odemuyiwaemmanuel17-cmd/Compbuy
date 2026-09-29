"""Buyer/seller negotiation threads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.utils.formatting import time_ago, truncate
from app.utils.parsing import as_datetime, as_str


@dataclass(frozen=True)
class Message:
    id: str
    conversation_id: str
    sender_id: str
    body: str
    created_at: datetime | None = None
    sender_name: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Message":
        sender = row.get("sender") if isinstance(row.get("sender"), dict) else {}
        return cls(
            id=as_str(row.get("id")),
            conversation_id=as_str(row.get("conversation_id")),
            sender_id=as_str(row.get("sender_id")),
            body=as_str(row.get("body")),
            created_at=as_datetime(row.get("created_at")),
            sender_name=as_str(sender.get("display_name")) or as_str(row.get("sender_name")),
        )

    @property
    def sent_ago(self) -> str:
        return time_ago(self.created_at)

    def authored_by(self, user_id: str | None) -> bool:
        return bool(user_id) and self.sender_id == user_id

    @property
    def author_label(self) -> str:
        return self.sender_name or "Member"


@dataclass(frozen=True)
class Conversation:
    id: str
    listing_id: str
    buyer_id: str
    seller_id: str
    created_at: datetime | None = None
    listing_title: str = ""
    buyer_name: str = ""
    seller_name: str = ""
    last_message_body: str = ""
    last_message_at: datetime | None = None
    message_count: int = 0

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Conversation":
        listing = row.get("listing") if isinstance(row.get("listing"), dict) else {}
        buyer = row.get("buyer") if isinstance(row.get("buyer"), dict) else {}
        seller = row.get("seller") if isinstance(row.get("seller"), dict) else {}
        last = row.get("last_message") if isinstance(row.get("last_message"), dict) else {}
        return cls(
            id=as_str(row.get("id")),
            listing_id=as_str(row.get("listing_id")),
            buyer_id=as_str(row.get("buyer_id")),
            seller_id=as_str(row.get("seller_id")),
            created_at=as_datetime(row.get("created_at")),
            listing_title=as_str(listing.get("title")) or as_str(row.get("listing_title")),
            buyer_name=as_str(buyer.get("display_name")) or as_str(row.get("buyer_name")),
            seller_name=as_str(seller.get("display_name")) or as_str(row.get("seller_name")),
            last_message_body=as_str(last.get("body")) or as_str(row.get("last_message_body")),
            last_message_at=as_datetime(last.get("created_at"))
            if last.get("created_at")
            else (
                as_datetime(row.get("last_message_at"))
                if row.get("last_message_at")
                else None
            ),
            message_count=int(row.get("message_count") or 0),
        )

    def includes(self, user_id: str | None) -> bool:
        return bool(user_id) and user_id in {self.buyer_id, self.seller_id}

    def counterparty_name(self, user_id: str) -> str:
        return self.seller_name if user_id == self.buyer_id else self.buyer_name or "Buyer"

    @property
    def preview(self) -> str:
        return truncate(self.last_message_body, 90) or "No messages yet"

    @property
    def updated_ago(self) -> str:
        return time_ago(self.last_message_at or self.created_at)

"""Offer input validation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

MAX_OFFER_MESSAGE_LENGTH = 2_000


class OfferCreate(BaseModel):
    amount: int = Field(gt=0)
    message: str = Field(default="", max_length=MAX_OFFER_MESSAGE_LENGTH)

    @field_validator("message", mode="before")
    @classmethod
    def _strip(cls, value: object) -> str:
        return str(value or "").strip()

    def to_values(self, *, listing_id: str, buyer_id: str, seller_id: str, currency: str) -> dict[str, Any]:
        return {
            "listing_id": listing_id,
            "buyer_id": buyer_id,
            "seller_id": seller_id,
            "amount": self.amount,
            "message": self.message,
            "currency": currency,
            "status": "pending",
        }

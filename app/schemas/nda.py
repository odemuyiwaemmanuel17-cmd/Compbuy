"""NDA request and signature validation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

MIN_REQUEST_MESSAGE_LENGTH = 10
MAX_REQUEST_MESSAGE_LENGTH = 2_000
MIN_SIGNER_NAME_LENGTH = 2
MAX_SIGNER_NAME_LENGTH = 120


class NdaRequestForm(BaseModel):
    """Buyer's note when asking for data-room access.

    Required with a minimum length: a seller has to judge credibility from this
    note before approving, so a blank request would only move the work elsewhere.
    """

    message: str = Field(min_length=MIN_REQUEST_MESSAGE_LENGTH, max_length=MAX_REQUEST_MESSAGE_LENGTH)

    @field_validator("message", mode="before")
    @classmethod
    def _strip(cls, value: object) -> str:
        return str(value or "").strip()

    def to_values(
        self, *, listing_id: str, buyer_id: str, seller_id: str
    ) -> dict[str, Any]:
        return {
            "listing_id": listing_id,
            "buyer_id": buyer_id,
            "seller_id": seller_id,
            "message": self.message,
            "status": "pending",
            "signed_name": "",
        }


class NdaSignForm(BaseModel):
    """The name typed by the buyer to countersign."""

    full_name: str = Field(min_length=MIN_SIGNER_NAME_LENGTH, max_length=MAX_SIGNER_NAME_LENGTH)

    @field_validator("full_name", mode="before")
    @classmethod
    def _strip(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("full_name")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value:
            raise ValueError("enter your full legal name")
        return value

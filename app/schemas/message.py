"""Message input validation."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

MIN_BODY_LENGTH = 1
MAX_BODY_LENGTH = 4_000


class MessageCreate(BaseModel):
    body: str = Field(min_length=MIN_BODY_LENGTH, max_length=MAX_BODY_LENGTH)

    @field_validator("body", mode="before")
    @classmethod
    def _strip(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("body")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value:
            raise ValueError("message cannot be blank")
        return value

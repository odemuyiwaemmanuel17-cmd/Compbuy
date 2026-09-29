"""Listing input validation and catalogue filter parsing."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import quote

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic import ValidationError as PydanticValidationError

from app.errors import ValidationError
from app.models.enums import ListingCategory, ListingStatus

MIN_TITLE_LENGTH = 6
MAX_TITLE_LENGTH = 120
MIN_DESCRIPTION_LENGTH = 30
MAX_DESCRIPTION_LENGTH = 20_000
MAX_ONE_LINER_LENGTH = 160
MIN_ESTABLISHED_YEAR = 1900

SortKey = Literal["newest", "price_asc", "price_desc", "revenue_desc"]


class ListingInput(BaseModel):
    """Fields shared by create and update."""

    title: str = Field(min_length=MIN_TITLE_LENGTH, max_length=MAX_TITLE_LENGTH)
    one_liner: str = Field(default="", max_length=MAX_ONE_LINER_LENGTH)
    description: str = Field(min_length=MIN_DESCRIPTION_LENGTH, max_length=MAX_DESCRIPTION_LENGTH)
    category: ListingCategory = ListingCategory.OTHER
    asking_price: int = Field(gt=0)
    annual_revenue: int = Field(ge=0)
    annual_profit: int | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", pattern=r"^[A-Za-z]{3}$")
    country: str = Field(default="", max_length=60)
    city: str = Field(default="", max_length=60)
    established_year: int | None = Field(default=None, ge=MIN_ESTABLISHED_YEAR)

    @field_validator("title", "one_liner", "description", "country", "city", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("currency", mode="before")
    @classmethod
    def _upper_currency(cls, value: object) -> str:
        return str(value or "USD").strip().upper()

    @model_validator(mode="after")
    def _check_year_in_range(self) -> "ListingInput":
        if self.established_year is not None:
            ceiling = datetime.now(timezone.utc).year + 1
            if self.established_year > ceiling:
                raise ValueError(f"established year cannot be later than {ceiling}")
        return self


class ListingCreate(ListingInput):
    def to_values(self, *, seller_id: str, status: ListingStatus) -> dict[str, Any]:
        return self._values(seller_id=seller_id, status=status)

    def _values(self, *, seller_id: str, status: ListingStatus) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        payload["category"] = self.category.value
        payload["status"] = status.value
        payload["seller_id"] = seller_id
        if self.annual_profit is None:
            payload["annual_profit"] = None
        return payload


class ListingUpdate(ListingCreate):
    status: ListingStatus = ListingStatus.DRAFT

    def to_values(self, *, seller_id: str) -> dict[str, Any]:
        payload = super().to_values(seller_id=seller_id, status=self.status)
        # A seller may not silently move a listing to another owner.
        payload.pop("seller_id", None)
        return payload


class ListingFilters(BaseModel):
    """Parsed, normalised query-string filters for the catalogue."""

    q: str = Field(default="", max_length=120)
    category: str = Field(default="")
    min_price: int | None = Field(default=None, ge=0)
    max_price: int | None = Field(default=None, ge=0)
    revenue_min: int | None = Field(default=None, ge=0)
    sort: SortKey = "newest"
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=12, ge=1, le=50)

    @field_validator("q", "category", mode="before")
    @classmethod
    def _strip(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("category")
    @classmethod
    def _normalise_category(cls, value: str) -> str:
        if not value:
            return ""
        try:
            return ListingCategory(value.lower()).value
        except ValueError:
            raise ValueError("unknown category") from None

    @model_validator(mode="after")
    def _check_price_band(self) -> "ListingFilters":
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.max_price < self.min_price
        ):
            raise ValueError("max price must be greater than or equal to min price")
        return self

    @property
    def has_active_filters(self) -> bool:
        return bool(
            self.q
            or self.category
            or self.min_price is not None
            or self.max_price is not None
            or self.revenue_min is not None
            or self.sort != "newest"
        )

    def as_query_string(self, *, page: int | None = None) -> str:
        """Re-serialise these filters for pagination links."""
        parts: list[str] = []
        for key, value in self.model_dump(exclude={"per_page", "page"}).items():
            if value is None or value == "":
                continue
            parts.append(f"{key}={quote(str(value))}")
        target_page = page if page is not None else self.page
        if target_page > 1:
            parts.append(f"page={target_page}")
        return "&".join(parts)

    @classmethod
    def from_request(cls, values: dict[str, Any], *, per_page: int) -> "ListingFilters":
        cleaned = {key: value for key, value in values.items() if value not in (None, "")}
        cleaned["per_page"] = per_page
        try:
            return cls.model_validate(cleaned)
        except PydanticValidationError as exc:
            error = ValidationError("Fix the highlighted filters to continue searching.")
            for item in exc.errors():
                location = ".".join(str(part) for part in item.get("loc", ())) or "filters"
                error.add_field_error(location, str(item.get("msg", "invalid value")))
            raise error from exc


__all__ = [
    "ListingCreate",
    "ListingFilters",
    "ListingInput",
    "ListingUpdate",
    "SortKey",
]

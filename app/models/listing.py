"""A business put up for sale."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models.enums import ListingStatus, category_label
from app.utils.formatting import format_money, format_ratio, time_ago, truncate
from app.utils.parsing import (
    as_datetime,
    as_opt_int,
    as_str,
    as_str_list,
)


@dataclass(frozen=True)
class Listing:
    id: str
    seller_id: str
    title: str
    one_liner: str = ""
    description: str = ""
    category: str = "other"
    asking_price: int = 0
    annual_revenue: int = 0
    annual_profit: int | None = None
    currency: str = "USD"
    country: str = ""
    city: str = ""
    established_year: int | None = None
    status: ListingStatus = ListingStatus.DRAFT
    image_urls: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Joined from ``profiles`` when the row is fetched with a seller lookup.
    seller_name: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Listing":
        seller_join = row.get("seller") if isinstance(row.get("seller"), dict) else None
        return cls(
            id=as_str(row.get("id")),
            seller_id=as_str(row.get("seller_id")),
            title=as_str(row.get("title")),
            one_liner=as_str(row.get("one_liner")),
            description=as_str(row.get("description")),
            category=as_str(row.get("category"), default="other"),
            asking_price=int(row.get("asking_price") or 0),
            annual_revenue=int(row.get("annual_revenue") or 0),
            annual_profit=as_opt_int(row.get("annual_profit")),
            currency=as_str(row.get("currency"), default="USD").upper(),
            country=as_str(row.get("country")),
            city=as_str(row.get("city")),
            established_year=as_opt_int(row.get("established_year")),
            status=cls._parse_status(row.get("status")),
            image_urls=as_str_list(row.get("image_urls")),
            created_at=as_datetime(row.get("created_at")),
            updated_at=as_datetime(row.get("updated_at")) if row.get("updated_at") else None,
            seller_name=as_str((seller_join or {}).get("display_name"))
            or as_str(row.get("seller_name")),
        )

    @staticmethod
    def _parse_status(raw: Any) -> ListingStatus:
        try:
            return ListingStatus(as_str(raw, default="draft"))
        except ValueError:
            return ListingStatus.DRAFT

    @property
    def is_published(self) -> bool:
        return self.status.is_visible_publicly

    @property
    def category_label(self) -> str:
        return category_label(self.category)

    @property
    def price_display(self) -> str:
        return format_money(self.asking_price, currency=self.currency)

    @property
    def price_display_compact(self) -> str:
        return format_money(self.asking_price, currency=self.currency, compact=True)

    @property
    def revenue_display_compact(self) -> str:
        return format_money(self.annual_revenue, currency=self.currency, compact=True)

    @property
    def revenue_multiple(self) -> str:
        return format_ratio(self.asking_price, self.annual_revenue)

    @property
    def profit_margin(self) -> str:
        if not self.annual_profit or not self.annual_revenue:
            return "—"
        return f"{(self.annual_profit / self.annual_revenue) * 100:.0f}%"

    @property
    def location(self) -> str:
        return ", ".join(part for part in (self.city, self.country) if part)

    @property
    def summary(self) -> str:
        return self.one_liner or truncate(self.description, 140)

    @property
    def posted_ago(self) -> str:
        return time_ago(self.created_at)

    def editable_by(self, user_id: str | None) -> bool:
        return bool(user_id) and self.seller_id == user_id

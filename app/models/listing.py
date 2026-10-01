"""A business put up for sale.

Financial sensitivity is handled here rather than in templates: every gated
figure is exposed only through a property that returns a placeholder until the
listing is marked ``data_room_unlocked``. A new template therefore cannot leak
revenue by reading the wrong attribute.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from app.models.enums import ListingStatus, RevenueBand, band_from_raw, category_label
from app.utils.formatting import format_money, format_ratio, time_ago, truncate
from app.utils.parsing import as_datetime, as_opt_int, as_str, as_str_list

LOCKED_PLACEHOLDER = "Members only"


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
    seller_name: str = ""
    # --- data-room fields (exact name, monthly figures, reason for selling) ---
    business_name: str = ""
    monthly_revenue: int | None = None
    net_profit: int | None = None
    reason_for_selling: str = ""
    revenue_band: RevenueBand = RevenueBand.UNDISCLOSED
    # True only when the viewer holds a signed NDA for this listing, or owns it.
    data_room_unlocked: bool = False

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Listing:
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
            business_name=as_str(row.get("business_name")),
            monthly_revenue=as_opt_int(row.get("monthly_revenue")),
            net_profit=as_opt_int(row.get("net_profit")),
            reason_for_selling=as_str(row.get("reason_for_selling")),
            revenue_band=band_from_raw(row.get("revenue_band")),
        )

    @staticmethod
    def _parse_status(raw: Any) -> ListingStatus:
        try:
            return ListingStatus(as_str(raw, default="draft"))
        except ValueError:
            return ListingStatus.DRAFT

    # ------------------------------------------------------------- data room

    def unlocked_for(self, unlocked: bool) -> Listing:
        """Return this listing with the data room opened (or closed)."""
        return replace(self, data_room_unlocked=bool(unlocked))

    @property
    def is_locked(self) -> bool:
        return not self.data_room_unlocked

    @property
    def display_name(self) -> str:
        """Exact business name for NDA holders, public headline for everyone else."""
        if self.data_room_unlocked and self.business_name:
            return self.business_name
        return self.title

    # ---------------------------------------------------------------- public

    @property
    def is_published(self) -> bool:
        return self.status.is_visible_publicly

    @property
    def category_label(self) -> str:
        return category_label(self.category)

    @property
    def revenue_band_label(self) -> str:
        return self.revenue_band.label

    @property
    def price_display(self) -> str:
        return format_money(self.asking_price, currency=self.currency)

    @property
    def price_display_compact(self) -> str:
        return format_money(self.asking_price, currency=self.currency, compact=True)

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

    # ------------------------------------------------------------- gated view

    @property
    def monthly_revenue_display(self) -> str:
        if not self.data_room_unlocked:
            return LOCKED_PLACEHOLDER
        return format_money(self.monthly_revenue, currency=self.currency)

    @property
    def annual_revenue_display(self) -> str:
        if not self.data_room_unlocked:
            return LOCKED_PLACEHOLDER
        return format_money(self.annual_revenue, currency=self.currency)

    @property
    def annual_revenue_display_compact(self) -> str:
        if not self.data_room_unlocked:
            return LOCKED_PLACEHOLDER
        return format_money(self.annual_revenue, currency=self.currency, compact=True)

    @property
    def net_profit_display(self) -> str:
        if not self.data_room_unlocked:
            return LOCKED_PLACEHOLDER
        return format_money(self.net_profit, currency=self.currency)

    @property
    def annual_profit_display(self) -> str:
        if not self.data_room_unlocked:
            return LOCKED_PLACEHOLDER
        return format_money(self.annual_profit, currency=self.currency)

    @property
    def revenue_multiple(self) -> str:
        """Gated: asking price divided by a public multiple reconstructs revenue."""
        if not self.data_room_unlocked:
            return LOCKED_PLACEHOLDER
        return format_ratio(self.asking_price, self.annual_revenue)

    @property
    def profit_margin(self) -> str:
        if not self.data_room_unlocked:
            return LOCKED_PLACEHOLDER
        # Sellers enter monthly figures; either pair yields the same margin.
        if self.monthly_revenue and self.net_profit is not None:
            return f"{(self.net_profit / self.monthly_revenue) * 100:.0f}%"
        if self.annual_profit and self.annual_revenue:
            return f"{(self.annual_profit / self.annual_revenue) * 100:.0f}%"
        return "—"

    @property
    def reason_for_selling_display(self) -> str:
        if not self.data_room_unlocked:
            return LOCKED_PLACEHOLDER
        return self.reason_for_selling or "Not stated"

    @property
    def gated_figure_count(self) -> int:
        """How many data-room values exist, for the locked teaser copy."""
        values = (self.monthly_revenue, self.net_profit, self.annual_profit, self.reason_for_selling)
        return sum(1 for value in values if value not in (None, "", 0))

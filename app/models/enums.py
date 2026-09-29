"""Domain enums shared by the database schema and the UI."""

from __future__ import annotations

from enum import StrEnum


class ListingStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    SOLD = "sold"
    ARCHIVED = "archived"

    @property
    def is_visible_publicly(self) -> bool:
        return self is ListingStatus.PUBLISHED


class OfferStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"

    @property
    def is_terminal(self) -> bool:
        return self in {OfferStatus.ACCEPTED, OfferStatus.DECLINED}


class ListingCategory(StrEnum):
    SAAS = "saas"
    ECOMMERCE = "ecommerce"
    CONTENT = "content"
    AGENCY = "agency"
    MARKETPLACE = "marketplace"
    SOFTWARE = "software"
    OTHER = "other"

    @property
    def label(self) -> str:
        return _CATEGORY_LABELS[self]


_CATEGORY_LABELS: dict[ListingCategory, str] = {
    ListingCategory.SAAS: "SaaS",
    ListingCategory.ECOMMERCE: "E-commerce",
    ListingCategory.CONTENT: "Content & Media",
    ListingCategory.AGENCY: "Agency",
    ListingCategory.MARKETPLACE: "Marketplace",
    ListingCategory.SOFTWARE: "Custom Software",
    ListingCategory.OTHER: "Other",
}

CATEGORY_CHOICES: list[tuple[str, str]] = [
    (value.value, value.label) for value in ListingCategory
]


def category_label(raw: str | None) -> str:
    """Label for a stored category value, tolerating legacy or unknown data."""
    if not raw:
        return "Other"
    try:
        return ListingCategory(raw).label
    except ValueError:
        return raw.replace("_", " ").title()

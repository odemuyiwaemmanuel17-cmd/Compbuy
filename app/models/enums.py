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


class OfferKind(StrEnum):
    """A firm offer, or a non-binding letter of intent."""

    OFFER = "offer"
    LOI = "loi"

    @property
    def label(self) -> str:
        return "Letter of intent" if self is OfferKind.LOI else "Offer"


class NdaStatus(StrEnum):
    """NDA lifecycle. Only SIGNED unlocks the data room."""

    PENDING = "pending"
    APPROVED = "approved"
    SIGNED = "signed"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"

    @property
    def unlocks_data_room(self) -> bool:
        return self is NdaStatus.SIGNED

    @property
    def is_open(self) -> bool:
        """Still actionable by one of the parties."""
        return self in {NdaStatus.PENDING, NdaStatus.APPROVED}

    @property
    def label(self) -> str:
        return _NDA_LABELS[self]


_NDA_LABELS: dict[NdaStatus, str] = {
    NdaStatus.PENDING: "Awaiting seller approval",
    NdaStatus.APPROVED: "Approved — your signature needed",
    NdaStatus.SIGNED: "Signed",
    NdaStatus.REJECTED: "Declined",
    NdaStatus.WITHDRAWN: "Withdrawn",
}


class RevenueBand(StrEnum):
    """Coarse, publicly visible revenue scale.

    Exact revenue is data-room only; a band keeps listings comparable without
    exposing figures or letting the multiple reconstruct them.
    """

    UNDISCLOSED = "undisclosed"
    UNDER_250K = "under_250k"
    _250K_TO_1M = "250k_to_1m"
    _1M_TO_5M = "1m_to_5m"
    OVER_5M = "over_5m"

    @property
    def label(self) -> str:
        return _BAND_LABELS[self]


_BAND_LABELS: dict[RevenueBand, str] = {
    RevenueBand.UNDISCLOSED: "Undisclosed",
    RevenueBand.UNDER_250K: "Under $250K / yr",
    RevenueBand._250K_TO_1M: "$250K–$1M / yr",
    RevenueBand._1M_TO_5M: "$1M–$5M / yr",
    RevenueBand.OVER_5M: "$5M+ / yr",
}


_BAND_ORDER: tuple[RevenueBand, ...] = (
    RevenueBand.UNDER_250K,
    RevenueBand._250K_TO_1M,
    RevenueBand._1M_TO_5M,
    RevenueBand.OVER_5M,
)

# Filter choices: "this band or higher". Undisclosed is never a floor because it
# carries no magnitude, and it is excluded from every floor.
BAND_FLOOR_LABELS: dict[RevenueBand, str] = {
    RevenueBand.UNDER_250K: "Any disclosed revenue",
    RevenueBand._250K_TO_1M: "$250K+ / yr",
    RevenueBand._1M_TO_5M: "$1M+ / yr",
    RevenueBand.OVER_5M: "$5M+ / yr",
}

BAND_FLOOR_CHOICES: list[tuple[str, str]] = [
    (band.value, BAND_FLOOR_LABELS[band]) for band in _BAND_ORDER
]

BAND_FLOOR_VALUES: list[str] = [band.value for band in _BAND_ORDER]


def bands_at_or_above(band: RevenueBand) -> list[str]:
    """Every comparable band from ``band`` upwards, for catalogue filtering."""
    try:
        index = _BAND_ORDER.index(band)
    except ValueError:
        return []
    return [item.value for item in _BAND_ORDER[index:]]


def revenue_band_for(annual_revenue: int | None) -> RevenueBand:
    """Map an annual figure to its public band."""
    value = annual_revenue or 0
    if value <= 0:
        return RevenueBand.UNDISCLOSED
    if value < 250_000:
        return RevenueBand.UNDER_250K
    if value < 1_000_000:
        return RevenueBand._250K_TO_1M
    if value < 5_000_000:
        return RevenueBand._1M_TO_5M
    return RevenueBand.OVER_5M


def band_from_raw(raw: object) -> RevenueBand:
    """Stored band value, tolerating absent or legacy data."""
    text = str(raw or "").strip()
    if not text:
        return RevenueBand.UNDISCLOSED
    try:
        return RevenueBand(text)
    except ValueError:
        return RevenueBand.UNDISCLOSED


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

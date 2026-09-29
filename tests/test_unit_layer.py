"""Unit layer: pure helpers, entity parsing, and filter semantics.

These run without the HTTP stack or the gateway.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.errors import ValidationError
from app.models.enums import ListingStatus, OfferStatus, category_label
from app.models.listing import Listing
from app.models.offer import Offer
from app.models.user import User
from app.rendering import safe_next
from app.schemas.listing import ListingCreate, ListingFilters
from app.utils.formatting import format_money, format_ratio, time_ago, truncate
from app.utils.parsing import as_datetime, as_int, as_opt_int, as_str_list
from app.utils.validation import field_errors


# ------------------------------------------------------------------ formatting

def test_format_money_compact_abbreviates_large_values() -> None:
    assert format_money(780000, compact=True) == "$780K"
    assert format_money(1250000, compact=True) == "$1.25M"
    assert format_money(1500000, compact=True) == "$1.5M"


def test_format_money_full_and_currency_symbols() -> None:
    assert format_money(780000) == "$780,000"
    assert format_money(500, currency="EUR") == "€500"
    assert format_money(None) == "—"


def test_format_money_compact_keeps_small_values_exact() -> None:
    assert format_money(999, compact=True) == "$999"


def test_format_ratio_guards_zero_and_missing_denominator() -> None:
    assert format_ratio(780000, 240000) == "3.2x"
    assert format_ratio(780000, 0) == "—"
    assert format_ratio(None, 100) == "—"


def test_time_ago_buckets() -> None:
    now = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
    assert time_ago(now - timedelta(seconds=10), now=now) == "just now"
    assert time_ago(now - timedelta(minutes=5), now=now) == "5 minutes ago"
    assert time_ago(now - timedelta(minutes=1), now=now) == "1 minute ago"
    assert time_ago(now - timedelta(hours=3), now=now) == "3 hours ago"
    assert time_ago(now - timedelta(days=9), now=now) == "9 days ago"
    assert time_ago(now - timedelta(days=400), now=now) == "1 year ago"
    assert time_ago(None) == ""


def test_time_ago_treats_a_future_timestamp_as_just_now() -> None:
    now = datetime(2026, 9, 29, tzinfo=timezone.utc)
    assert time_ago(now + timedelta(days=3), now=now) == "just now"


def test_truncate_collapses_whitespace_and_adds_ellipsis() -> None:
    assert truncate("a  b\n c", limit=10) == "a b c"
    assert truncate("x" * 30, limit=10).endswith("…")
    assert truncate("", limit=10) == ""


# --------------------------------------------------------------------- parsing

def test_as_int_accepts_numeric_strings_and_rejects_junk() -> None:
    assert as_int("1000") == 1000
    assert as_int(1000.7) == 1001
    assert as_int("", default=7) == 7
    assert as_int("nope", default=7) == 7
    assert as_int(None, default=3) == 3


def test_as_opt_int_returns_none_for_absent_values() -> None:
    assert as_opt_int(None) is None
    assert as_opt_int("") is None
    assert as_opt_int("1999") == 1999


def test_as_datetime_parses_offsets_and_falls_back_to_now() -> None:
    parsed = as_datetime("2026-01-31T10:00:00Z")
    assert parsed.year == 2026 and parsed.tzinfo is not None
    assert as_datetime("garbage").year >= 2026
    assert as_datetime(None).tzinfo is not None


def test_as_str_list_handles_arrays_and_comma_strings() -> None:
    assert as_str_list(["a", "", "b"]) == ["a", "b"]
    assert as_str_list("a, b") == ["a", "b"]
    assert as_str_list(None) == []


# -------------------------------------------------------------------- entities

def test_listing_from_row_maps_status_and_display_fields() -> None:
    listing = Listing.from_row(
        {
            "id": "l1",
            "seller_id": "s1",
            "title": "Ledgerly",
            "category": "saas",
            "asking_price": 780000,
            "annual_revenue": 240000,
            "annual_profit": 96000,
            "status": "published",
            "city": "Lisbon",
            "country": "Portugal",
        }
    )
    assert listing.status is ListingStatus.PUBLISHED
    assert listing.is_published
    assert listing.revenue_multiple == "3.2x"
    assert listing.profit_margin == "40%"
    assert listing.location == "Lisbon, Portugal"
    assert listing.category_label == "SaaS"
    assert listing.editable_by("s1")
    assert not listing.editable_by("other")


def test_listing_from_row_survives_unknown_and_missing_status() -> None:
    listing = Listing.from_row({"id": "l2", "status": "exploded", "asking_price": None})
    assert listing.status is ListingStatus.DRAFT
    assert listing.asking_price == 0
    assert not listing.is_published
    assert listing.profit_margin == "—"


def test_offer_from_row_and_decision_helpers() -> None:
    offer = Offer.from_row(
        {"id": "o1", "listing_id": "l1", "buyer_id": "b1", "seller_id": "s1", "amount": 700000, "status": "pending"}
    )
    assert offer.amount_display == "$700,000"
    assert not offer.is_decided
    assert offer.decidable_by("s1")
    assert not offer.decidable_by("b1")
    assert offer.is_for("b1")
    assert not offer.is_for("stranger")

    decided = Offer.from_row({**offer.__dict__, "id": "o2", "status": "accepted"})
    assert decided.is_decided
    assert not decided.decidable_by("s1")


def test_user_name_and_initials_fallback_chain() -> None:
    named = User(id="u1", email="a@b.com", display_name="Priya Nair")
    assert named.name == "Priya Nair"
    assert named.initials == "PN"

    anonymous = User(id="u2", email="dana@b.com")
    assert anonymous.name == "dana"
    assert anonymous.owns("u2")
    assert not anonymous.owns(None)


def test_category_label_tolerates_legacy_values() -> None:
    assert category_label("ecommerce") == "E-commerce"
    assert category_label("some_legacy_key") == "Some Legacy Key"
    assert category_label(None) == "Other"


def test_offer_status_and_listing_status_semantics() -> None:
    assert ListingStatus.PUBLISHED.is_visible_publicly
    assert not ListingStatus.DRAFT.is_visible_publicly
    assert OfferStatus.ACCEPTED.is_terminal
    assert not OfferStatus.PENDING.is_terminal


# ------------------------------------------------------------------- filters

def make_filters(**values: object) -> ListingFilters:
    return ListingFilters.model_validate({"per_page": 12, **values})


def test_filters_reject_inverted_price_band() -> None:
    with pytest.raises(PydanticValidationError) as exc:
        make_filters(min_price=500000, max_price=100000)
    assert "max price" in str(exc.value).lower()


def test_filters_normalise_category_case() -> None:
    assert make_filters(category="SaaS").category == "saas"


def test_filters_reject_unknown_category() -> None:
    with pytest.raises(PydanticValidationError):
        make_filters(category="watches")


def test_filters_query_string_keeps_values_and_advances_page() -> None:
    filters = make_filters(q="lead gen", category="agency", min_price=1000, page=2)
    query = filters.as_query_string(page=3)

    assert "page=3" in query
    assert "category=agency" in query
    assert "min_price=1000" in query
    assert "q=lead%20gen" in query
    assert "per_page" not in query


def test_filters_query_string_omits_page_one() -> None:
    assert "page=" not in make_filters(category="saas").as_query_string()


def test_filters_page_floor_is_enforced() -> None:
    with pytest.raises(PydanticValidationError):
        make_filters(page=0)


def test_from_request_translates_bad_input_into_app_validation_error() -> None:
    with pytest.raises(ValidationError) as exc:
        ListingFilters.from_request({"page": "banana"}, per_page=12)
    assert "page" in exc.value.field_errors


def test_has_active_filters_flag() -> None:
    assert not make_filters().has_active_filters
    assert make_filters(sort="price_asc").has_active_filters


# ---------------------------------------------------------------- create schema

def test_listing_create_rejects_non_positive_price_and_short_title() -> None:
    base = {
        "title": "A valid listing title",
        "description": "Long enough description to satisfy the minimum length rule.",
        "asking_price": 1,
        "annual_revenue": 0,
    }
    ListingCreate.model_validate(base)

    for broken in ({"asking_price": 0}, {"asking_price": -5}, {"title": "tiny"}, {"description": "short"}):
        with pytest.raises(PydanticValidationError):
            ListingCreate.model_validate({**base, **broken})


def test_listing_create_values_pin_seller_and_status() -> None:
    values = ListingCreate.model_validate(
        {
            "title": "A valid listing title",
            "description": "Long enough description to satisfy the minimum length rule.",
            "asking_price": 150000,
            "annual_revenue": 60000,
            "category": "saas",
        }
    ).to_values(seller_id="s1", status=ListingStatus.PUBLISHED)

    assert values["seller_id"] == "s1"
    assert values["status"] == "published"
    assert values["category"] == "saas"
    assert values["annual_profit"] is None


def test_listing_create_uppercases_currency_and_strips_text() -> None:
    created = ListingCreate.model_validate(
        {
            "title": "  Padded title here  ",
            "description": "Description text that is comfortably long enough.",
            "asking_price": 90000,
            "annual_revenue": 10000,
            "currency": "eur",
            "city": "  Porto ",
        }
    )
    assert created.title == "Padded title here"
    assert created.city == "Porto"
    assert created.currency == "EUR"


def test_established_year_upper_bound_tracks_this_year() -> None:
    ceiling = datetime.now(timezone.utc).year + 2
    with pytest.raises(PydanticValidationError):
        ListingCreate.model_validate(
            {
                "title": "Valid title here",
                "description": "Description text that is comfortably long enough.",
                "asking_price": 100,
                "annual_revenue": 10,
                "established_year": ceiling,
            }
        )


# ---------------------------------------------------------------- open redirect

def test_safe_next_allows_only_site_relative_paths() -> None:
    assert safe_next("/buyer/offers") == "/buyer/offers"
    assert safe_next("//evil.example.com") == "/"
    assert safe_next("https://evil.example.com") == "/"
    assert safe_next("javascript:alert(1)") == "/"
    assert safe_next("") == "/"
    assert safe_next(None) == "/"


def test_safe_next_truncates_overlong_targets() -> None:
    assert len(safe_next("/" + "a" * 400)) <= 200


# ------------------------------------------------------------- error translation

def test_field_errors_maps_pydantic_locations_to_field_names() -> None:
    with pytest.raises(PydanticValidationError) as exc:
        ListingCreate.model_validate({"title": "x", "asking_price": -1})

    mapped = field_errors(exc.value)
    assert "title" in mapped
    assert "asking_price" in mapped
    assert any("short" in message for message in mapped["title"])


def test_field_errors_passes_through_app_validation_errors() -> None:
    error = ValidationError("nope")
    error.add_field_error("category", "unknown category")
    assert field_errors(error) == {"category": ["unknown category"]}

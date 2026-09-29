"""AC-2: public catalogue search, filtering, sorting, and pagination."""

from __future__ import annotations

from tests.conftest import create_listing


def _seed_catalogue(seller, buyer) -> dict[str, str]:
    """Publish a small spread of listings across two sellers."""
    return {
        "saas_big": create_listing(
            seller,
            title="Ledgerly bookkeeping SaaS",
            category="saas",
            asking_price="780000",
            annual_revenue="240000",
            description="Accounting tool for freelancers with strong retention numbers.",
        ),
        "saas_small": create_listing(
            buyer,
            title="RetainIQ churn analytics",
            category="saas",
            asking_price="180000",
            annual_revenue="64000",
            description="Django analytics for subscription box operators.",
        ),
        "content": create_listing(
            buyer,
            title="Northwind content portfolio",
            category="content",
            asking_price="265000",
            annual_revenue="118000",
            description="Three content sites monetised through display advertising.",
        ),
        "ecommerce": create_listing(
            buyer,
            title="Kettle and Co coffee roaster",
            category="ecommerce",
            asking_price="310000",
            annual_revenue="145000",
            description="Subscription-led coffee ecommerce brand with a roastery contract.",
        ),
    }


def test_browse_shows_only_published_listings_with_total_count(app, client, seller, buyer) -> None:
    """AC-2 happy path."""
    ids = _seed_catalogue(seller, buyer)
    hidden = create_listing(seller, publish=False, title="Unpublished draft headline here")

    response = client.get("/listings")
    assert response.status_code == 200
    assert "4 result" in response.text
    for key, listing_id in ids.items():
        assert listing_id in response.text, key
    assert hidden not in response.text


def test_category_filter_narrows_results(app, client, seller, buyer) -> None:
    ids = _seed_catalogue(seller, buyer)

    response = client.get("/listings", params={"category": "saas"})
    assert ids["saas_big"] in response.text
    assert ids["saas_small"] in response.text
    assert ids["content"] not in response.text
    assert "2 result" in response.text


def test_price_band_filter_applies_both_bounds(app, client, seller, buyer) -> None:
    ids = _seed_catalogue(seller, buyer)

    response = client.get("/listings", params={"min_price": "200000", "max_price": "300000"})

    assert ids["content"] in response.text
    assert ids["saas_big"] not in response.text
    assert ids["saas_small"] not in response.text
    assert ids["ecommerce"] not in response.text


def test_keyword_search_matches_title_and_description(app, client, seller, buyer) -> None:
    ids = _seed_catalogue(seller, buyer)

    by_title = client.get("/listings", params={"q": "Ledgerly"})
    assert ids["saas_big"] in by_title.text
    assert ids["content"] not in by_title.text

    by_description = client.get("/listings", params={"q": "advertising"})
    assert ids["content"] in by_description.text
    assert ids["saas_big"] not in by_description.text


def test_search_is_combined_across_every_predicate(app, client, seller, buyer) -> None:
    ids = _seed_catalogue(seller, buyer)

    response = client.get(
        "/listings", params={"q": "analytics", "category": "saas", "min_price": "100000"}
    )
    assert ids["saas_small"] in response.text
    assert "1 result" in response.text


def test_revenue_floor_filters_the_catalogue(app, client, seller, buyer) -> None:
    ids = _seed_catalogue(seller, buyer)

    response = client.get("/listings", params={"revenue_min": "150000"})
    assert ids["saas_big"] in response.text
    assert ids["content"] not in response.text


def test_sorting_by_price_both_directions(app, client, seller, buyer) -> None:
    ids = _seed_catalogue(seller, buyer)

    ascending = client.get("/listings", params={"sort": "price_asc"}).text
    descending = client.get("/listings", params={"sort": "price_desc"}).text

    order_asc = [ids[key] for key in ("saas_small", "content", "ecommerce", "saas_big")]
    order_desc = list(reversed(order_asc))

    def rank(html: str, listing_id: str) -> int:
        return html.index(listing_id)

    assert sorted(order_asc, key=lambda item: rank(ascending, item)) == order_asc
    assert sorted(order_desc, key=lambda item: rank(descending, item)) == order_desc


def test_pagination_splits_results_and_links_next_page(paged_app, seller) -> None:
    from fastapi.testclient import TestClient

    ids = [create_listing(seller, title=f"Business number {index} for sale") for index in range(1, 4)]

    with TestClient(paged_app) as public:
        # The catalogue default sort is newest first, so the most recent
        # listing leads page one and the oldest falls to page two.
        first = public.get("/listings")
        assert first.status_code == 200
        assert ids[2] in first.text
        assert ids[1] in first.text
        assert ids[0] not in first.text
        assert "3 listings" in first.text
        assert "page=2" in first.text

        second = public.get("/listings", params={"page": "2"})
        assert ids[0] in second.text
        assert ids[2] not in second.text


def test_pagination_links_preserve_active_filters(paged_app, seller) -> None:
    from fastapi.testclient import TestClient

    for index in range(1, 4):
        create_listing(seller, title=f"Business number {index} for sale", category="saas")

    with TestClient(paged_app) as public:
        page = public.get("/listings", params={"category": "saas", "q": "business", "page": "2"})

    assert "category=saas" in page.text
    assert "q=business" in page.text


def test_empty_result_set_renders_the_empty_state(app, client, seller) -> None:
    create_listing(seller)

    response = client.get("/listings", params={"q": "nothingmatches"})
    assert response.status_code == 200
    assert "No listings match these filters" in response.text
    assert "0 result" in response.text


def test_unknown_category_is_reported_not_crashing(app, client, seller) -> None:
    create_listing(seller)

    response = client.get("/listings", params={"category": "watches"})
    assert response.status_code == 422
    assert "category" in response.text


def test_inverted_price_band_is_reported(app, client) -> None:
    """AC-2 edge: max_price below min_price."""
    response = client.get("/listings", params={"min_price": "500000", "max_price": "100000"})
    assert response.status_code == 422
    assert "max price" in response.text.lower()


def test_negative_and_non_numeric_pages_are_rejected(app, client) -> None:
    assert client.get("/listings", params={"page": "0"}).status_code == 422
    assert client.get("/listings", params={"page": "banana"}).status_code == 422


def test_home_page_surfaces_latest_listings_and_counts(app, client, seller, buyer) -> None:
    ids = _seed_catalogue(seller, buyer)

    response = client.get("/")
    assert response.status_code == 200
    assert "4 verified business" in response.text
    assert ids["saas_big"] in response.text


def test_detail_page_renders_the_offer_form_for_anonymous_visitors(app, client, seller) -> None:
    listing_id = create_listing(seller)

    response = client.get(f"/listings/{listing_id}")
    assert response.status_code == 200
    assert "$780,000" in response.text
    assert "Sign in to make an offer" in response.text

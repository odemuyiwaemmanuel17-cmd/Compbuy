"""Jinja2 environment and template globals."""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.config import Settings
from app.models.enums import CATEGORY_CHOICES, ListingStatus
from app.utils.formatting import format_money, format_number, time_ago, truncate

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


class MarketplaceTemplates(Jinja2Templates):
    def __init__(self, settings: Settings) -> None:
        # ``Jinja2Templates`` enables autoescape for the filesystem loader itself.
        super().__init__(directory=str(TEMPLATES_DIR))
        self.env.globals.update(
            SITE_NAME=settings.site_name,
            CATEGORY_CHOICES=CATEGORY_CHOICES,
            LISTING_STATUS_CHOICES=[(s.value, s.value.capitalize()) for s in ListingStatus],
            format_money=format_money,
            format_number=format_number,
            time_ago=time_ago,
            truncate=truncate,
        )
        self.env.filters["money"] = format_money
        self.env.filters["number"] = format_number
        self.env.filters["ago"] = time_ago

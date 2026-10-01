"""Presentation-layer formatters used by templates and models."""

from __future__ import annotations

from datetime import datetime, timezone

_CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£"}
_LARGE = 1_000_000
_MEDIUM = 1_000


def currency_symbol(currency: str | None) -> str:
    return _CURRENCY_SYMBOLS.get((currency or "USD").upper(), "$")


def _trimmed(number: float, places: int) -> str:
    return f"{number:.{places}f}".rstrip("0").rstrip(".")


def format_money(amount: float | None, *, currency: str = "USD", compact: bool = False) -> str:
    """Render an amount as currency.

    ``compact`` produces catalogue-friendly output: 1250000 -> "$1.25M".
    """
    if amount is None:
        return "—"
    symbol = currency_symbol(currency)
    value = float(amount)
    magnitude = abs(value)
    if compact:
        if magnitude >= _LARGE:
            return f"{symbol}{_trimmed(value / _LARGE, 2)}M"
        if magnitude >= _MEDIUM:
            return f"{symbol}{_trimmed(value / _MEDIUM, 1)}K"
        return f"{symbol}{value:,.0f}"
    return f"{symbol}{value:,.0f}"


def format_number(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{float(value):,.0f}"


def format_ratio(numerator: float | None, denominator: float | None) -> str:
    """Multiple, guarded against zero and missing denominators."""
    if not numerator or not denominator:
        return "—"
    try:
        return f"{float(numerator) / float(denominator):.1f}x"
    except (TypeError, ValueError, ZeroDivisionError):
        return "—"


def time_ago(moment: datetime | None, *, now: datetime | None = None) -> str:
    if moment is None:
        return ""
    reference = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    delta_seconds = int((reference - moment).total_seconds())
    if delta_seconds < 0:
        return "just now"
    if delta_seconds < 60:
        return "just now"
    minutes = delta_seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    if days < 31:
        return f"{days} day{'s' if days != 1 else ''} ago"
    months = days // 30
    if months < 12:
        return f"{months} month{'s' if months != 1 else ''} ago"
    years = days // 365
    return f"{years} year{'s' if years != 1 else ''} ago"


def truncate(text: str | None, limit: int = 140) -> str:
    if not text:
        return ""
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)].rstrip() + "…"

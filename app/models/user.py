"""Marketplace participant, backed by the ``profiles`` table."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.utils.parsing import as_opt_str, as_str


@dataclass(frozen=True)
class User:
    id: str
    email: str
    display_name: str = ""
    company_name: str = ""
    location: str = ""

    @property
    def name(self) -> str:
        """Best available human label for this participant."""
        return self.display_name or self.email.split("@")[0] or "Member"

    @property
    def initials(self) -> str:
        source = self.display_name or self.email or "?"
        parts = [word[0] for word in source.replace("@", " ").split() if word]
        return "".join(parts[:2]).upper() or "?"

    def owns(self, owner_id: str | None) -> bool:
        return bool(owner_id) and owner_id == self.id

    @classmethod
    def from_profile(cls, user_id: str, row: dict[str, Any] | None) -> User:
        row = row or {}
        return cls(
            id=user_id,
            email=as_str(row.get("email")),
            display_name=as_str(row.get("display_name")),
            company_name=as_str(row.get("company_name")),
            location=as_opt_str(row.get("location")) or "",
        )

    @classmethod
    def blank(cls, user_id: str) -> User:
        return cls(id=user_id)

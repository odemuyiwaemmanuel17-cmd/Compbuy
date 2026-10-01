"""Auth form validation."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

MIN_PASSWORD_LENGTH = 10


class RegisterForm(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=200)
    password_confirm: str = Field(default="", max_length=200)
    display_name: str = Field(default="", max_length=80)

    @field_validator("email", mode="before")
    @classmethod
    def _clean_email(cls, value: object) -> str:
        text = str(value or "").strip().lower()
        if "@" not in text or text.startswith("@") or text.endswith("@"):
            raise ValueError("enter a valid email address")
        return text

    @field_validator("display_name", mode="before")
    @classmethod
    def _clean_name(cls, value: object) -> str:
        return str(value or "").strip()


class LoginForm(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)

    @field_validator("email", mode="before")
    @classmethod
    def _clean_email(cls, value: object) -> str:
        return str(value or "").strip().lower()

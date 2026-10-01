"""Supabase authentication plus the local ``profiles`` row that goes with it."""

from __future__ import annotations

import contextlib

from app.database import AuthSession, run_in_thread, run_query, translate_supabase_error
from app.errors import AppError, ExternalServiceError
from app.models.user import User
from app.services.base import BaseService

PROFILE_COLUMNS = "id, email, display_name, company_name, location"


class AuthService(BaseService):
    async def register(self, email: str, password: str, display_name: str) -> AuthSession:
        try:
            session = await run_in_thread(self.gateway.auth.sign_up, email, password)
        except AppError:
            raise
        except Exception as exc:  # supabase transport / api failure
            raise translate_supabase_error(exc, resource="account") from exc
        await self.upsert_profile(session.user.id, email=session.user.email or email, display_name=display_name)
        return session

    async def sign_in(self, email: str, password: str) -> AuthSession:
        try:
            session = await run_in_thread(self.gateway.auth.sign_in, email, password)
        except AppError:
            raise
        except Exception as exc:
            raise translate_supabase_error(exc, resource="account") from exc
        # Recover the profile written at sign-up time.
        await self.touch_profile(session.user.id, email=session.user.email)
        return session

    async def sign_out(self, access_token: str | None) -> None:
        if not access_token:
            return
        # Best-effort: the caller destroys the local session even if Supabase
        # cannot be reached, so a failed revoke must not trap the user in.
        with contextlib.suppress(Exception):
            await run_in_thread(self.gateway.auth.sign_out, access_token)

    async def load_user(self, user_id: str) -> User | None:
        result = await run_query(
            self.gateway.table("profiles").select(PROFILE_COLUMNS).eq("id", user_id).limit(1)
        )
        row = result.first
        if row is None:
            return None
        return User.from_profile(user_id, row)

    async def load_users_by_id(self, user_ids: set[str]) -> dict[str, User]:
        if not user_ids:
            return {}
        result = await run_query(
            self.gateway.table("profiles")
            .select(f"id, {PROFILE_COLUMNS}")
            .in_("id", sorted(user_ids))
        )
        return {row["id"]: User.from_profile(str(row["id"]), row) for row in result.rows if row.get("id")}

    async def upsert_profile(self, user_id: str, *, email: str, display_name: str = "") -> None:
        clean_name = (display_name or "").strip()
        values = {"id": user_id, "email": email, "display_name": clean_name or email.split("@")[0]}
        try:
            await run_query(self.gateway.table("profiles").upsert(values))
        except Exception as exc:
            raise ExternalServiceError(
                "We could not prepare your marketplace profile. Please try again."
            ) from exc

    async def touch_profile(self, user_id: str, *, email: str) -> None:
        """Guarantee a profile exists for a signing-in user without overwriting edits."""
        result = await run_query(
            self.gateway.table("profiles").select("id").eq("id", user_id).limit(1)
        )
        if result.first is None:
            await self.upsert_profile(user_id, email=email)

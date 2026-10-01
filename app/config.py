"""Runtime configuration, loaded from the environment with `python-dotenv`.

Nothing else in the codebase reads `os.environ` directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from functools import lru_cache

from dotenv import load_dotenv

_TRUTHY = {"1", "true", "yes", "on"}
SITE_NAME = "Compbuy"
DEFAULT_COOKIE_NAME = "compbuy_session"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUTHY


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _env_str(name: str, default: str = "") -> str:
    return (os.getenv(name) or "").strip() or default


def _normalise_url(raw: str | None) -> str | None:
    if raw is None:
        return None
    return raw.strip().rstrip("/") or None


@dataclass(frozen=True)
class Settings:
    """Resolved application settings.

    Supabase credentials are optional at construction time so the app can boot
    in test/CI environments. The gateway raises a clear error the first time a
    real Supabase call is attempted without them.
    """

    site_name: str = SITE_NAME
    environment: str = "development"
    debug: bool = True

    supabase_url: str | None = None
    supabase_anon_key: str | None = None
    supabase_service_role_key: str | None = None

    session_secret: str = ""
    session_cookie_name: str = DEFAULT_COOKIE_NAME
    session_max_age_seconds: int = 60 * 60 * 24 * 7
    cookie_secure: bool = False

    listings_per_page: int = 12
    max_listings_per_page: int = 50

    def __post_init__(self) -> None:
        if self.listings_per_page < 1:
            raise ValueError("listings_per_page must be >= 1")
        if self.max_listings_per_page < self.listings_per_page:
            raise ValueError("max_listings_per_page must be >= listings_per_page")
        if self.session_max_age_seconds < 60:
            raise ValueError("session_max_age_seconds must be >= 60")

    @property
    def has_supabase_credentials(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key)

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod", "staging"}

    def with_overrides(self, **changes: object) -> Settings:
        return replace(self, **changes)  # type: ignore[arg-type]

    def warning_list(self) -> list[str]:
        """Configuration problems that should not stop boot but must be surfaced."""
        warnings: list[str] = []
        if not self.has_supabase_credentials:
            warnings.append(
                "SUPABASE_URL / SUPABASE_ANON_KEY are not set; database and auth "
                "calls will fail until configured."
            )
        if not self.session_secret:
            warnings.append("SESSION_SECRET is not set; signed sessions are unavailable.")
        if self.is_production and not self.cookie_secure:
            warnings.append("COOKIE_SECURE should be true in production.")
        return warnings


def _deployed_environment() -> str:
    """Infer the environment from the host platform when APP_ENV is not set.

    Vercel injects ``VERCEL_ENV=production|preview|development``. Both deployed
    values must be treated as production: the container is shared and short-lived,
    so without a real ``SESSION_SECRET`` the app would fall back to an ephemeral key
    generated on every cold start and silently invalidate all session cookies.
    """
    return "production" if _env_str("VERCEL_ENV").lower() in {"production", "preview"} else "development"


def settings_from_env(*, dotenv_path: str | os.PathLike[str] | None = None) -> Settings:
    """Build settings from the process environment plus an optional `.env` file."""
    load_dotenv(dotenv_path, override=False)

    environment = _env_str("APP_ENV") or _deployed_environment()
    return Settings(
        site_name=_env_str("SITE_NAME", SITE_NAME),
        environment=environment,
        debug=_env_bool("APP_DEBUG", default=environment.lower() != "production"),
        supabase_url=_normalise_url(os.getenv("SUPABASE_URL")),
        supabase_anon_key=_env_str("SUPABASE_ANON_KEY") or None,
        supabase_service_role_key=_env_str("SUPABASE_SERVICE_ROLE_KEY") or None,
        session_secret=_env_str("SESSION_SECRET"),
        session_cookie_name=_env_str("SESSION_COOKIE_NAME", DEFAULT_COOKIE_NAME),
        session_max_age_seconds=_env_int("SESSION_MAX_AGE_SECONDS", 60 * 60 * 24 * 7),
        cookie_secure=_env_bool("COOKIE_SECURE", default=environment.lower() == "production"),
        listings_per_page=_env_int("LISTINGS_PER_PAGE", 12),
    )


def unconfigured_settings(
    *, secret: str = "insecure-test-session-secret", environment: str = "test"
) -> Settings:
    """Deterministic settings for tests and credential-free local runs."""
    return Settings(environment=environment, debug=True, session_secret=secret)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return settings_from_env()

"""FastAPI dependency providers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.config import Settings
from app.db import Gateway, get_gateway
from app.errors import AuthenticationError
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.listing_service import ListingService
from app.services.message_service import MessageService
from app.services.offer_service import OfferService
from app.services.watchlist_service import WatchlistService
from app.session_store import session_user_id

_USER_STATE_KEY = "compbuy_current_user"


def settings_dep(request: Request) -> Settings:
    """Always resolve settings from the app instance, so an injected
    configuration (tests, alternate deployments) is what routers actually see."""
    return request.app.state.settings


def gateway_dep() -> Gateway:
    return get_gateway()


SettingsDep = Annotated[Settings, Depends(settings_dep)]
GatewayDep = Annotated[Gateway, Depends(gateway_dep)]


def listing_service_dep(gateway: GatewayDep) -> ListingService:
    return ListingService(gateway)


def offer_service_dep(gateway: GatewayDep) -> OfferService:
    return OfferService(gateway)


def message_service_dep(gateway: GatewayDep) -> MessageService:
    return MessageService(gateway)


def watchlist_service_dep(gateway: GatewayDep) -> WatchlistService:
    return WatchlistService(gateway)


def auth_service_dep(gateway: GatewayDep) -> AuthService:
    return AuthService(gateway)


ListingServiceDep = Annotated[ListingService, Depends(listing_service_dep)]
OfferServiceDep = Annotated[OfferService, Depends(offer_service_dep)]
MessageServiceDep = Annotated[MessageService, Depends(message_service_dep)]
WatchlistServiceDep = Annotated[WatchlistService, Depends(watchlist_service_dep)]
AuthServiceDep = Annotated[AuthService, Depends(auth_service_dep)]


async def optional_user(request: Request, auth: AuthServiceDep) -> User | None:
    """Resolve the signed-in participant without failing the request.

    Cached on ``request.state`` so a page that needs the identity twice (for
    example a route plus a template global) issues a single profile query.
    """
    if hasattr(request.state, _USER_STATE_KEY):
        cached = getattr(request.state, _USER_STATE_KEY)
        return cached if isinstance(cached, User) else None

    user_id = session_user_id(request)
    if not user_id:
        setattr(request.state, _USER_STATE_KEY, None)
        return None

    profile = await auth.load_user(user_id)
    resolved = profile or User.blank(user_id)
    setattr(request.state, _USER_STATE_KEY, resolved)
    return resolved


async def require_user(
    request: Request, user: Annotated[User | None, Depends(optional_user)]
) -> User:
    """Guard for seller/buyer surfaces; unauthenticated requests redirect to login."""
    if user is None:
        raise AuthenticationError("Please sign in to continue.")
    return user


OptionalUserDep = Annotated[User | None, Depends(optional_user)]
CurrentUserDep = Annotated[User, Depends(require_user)]

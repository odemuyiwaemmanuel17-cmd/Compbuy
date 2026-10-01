"""Compbuy application factory."""

from __future__ import annotations

import logging
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import Settings, get_settings
from app.database import Gateway, SupabaseGateway, set_gateway
from app.errors import AppError
from app.rendering import error_response, templates_for
from app.routers import (
    auth,
    buyer,
    dashboard,
    listings,
    messages,
    nda,
    offers,
    pages,
    seller,
)
from app.templating import MarketplaceTemplates

logger = logging.getLogger("compbuy")

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _session_secret(settings: Settings) -> str:
    if settings.session_secret:
        return settings.session_secret
    if settings.is_production:
        raise RuntimeError(
            "SESSION_SECRET must be set in production. Generate one with: "
            "python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )
    logger.warning("SESSION_SECRET not set - using an ephemeral key; sessions end on restart.")
    return secrets.token_urlsafe(32)


def create_app(
    settings: Settings | None = None,
    gateway: Gateway | None = None,
    *,
    on_startup: Callable[[Settings], Awaitable[None]] | None = None,
) -> FastAPI:
    config = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        previous = None
        if gateway is not None:
            previous = set_gateway(gateway)
        elif config.has_supabase_credentials:
            try:
                previous = set_gateway(SupabaseGateway(config))
            except AppError as exc:
                logger.error("Supabase gateway initialisation failed: %s", exc.message)
        else:
            for problem in config.warning_list():
                logger.warning("Configuration: %s", problem)
        if on_startup is not None:
            await on_startup(config)
        try:
            yield
        finally:
            if previous is not None or gateway is not None:
                set_gateway(previous)

    app = FastAPI(
        title=config.site_name,
        description="Marketplace for buying and selling businesses.",
        version="1.0.0",
        debug=config.debug,
        lifespan=lifespan,
    )
    app.state.settings = config
    app.state.templates = MarketplaceTemplates(config)

    app.add_middleware(
        SessionMiddleware,
        secret_key=_session_secret(config),
        max_age=config.session_max_age_seconds,
        same_site="lax",
        https_only=config.cookie_secure,
    )

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError):
        response = error_response(request, exc)
        if _wants_json(request) and not isinstance(response, RedirectResponse):
            return JSONResponse({"error": exc.message, "fields": exc.field_errors}, status_code=exc.status_code)
        return response

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(request: Request, exc: RequestValidationError):
        if _wants_json(request):
            return JSONResponse({"error": "Invalid request.", "fields": exc.errors()}, status_code=422)
        response = templates_for(request).TemplateResponse(
            request=request,
            name="errors/error.html",
            context={
                "app_error": "The form was submitted incorrectly. Please review and try again.",
                "field_errors": {},
                "status_code": 422,
                "flash_messages": [],
                "current_path": request.url.path,
            },
        )
        response.status_code = 422
        return response

    @app.exception_handler(404)
    async def handle_not_found(request: Request, exc: Exception):
        response = templates_for(request).TemplateResponse(
            request=request,
            name="errors/404.html",
            context={
                "app_error": "We could not find that page.",
                "field_errors": {},
                "status_code": 404,
                "flash_messages": [],
                "current_path": request.url.path,
            },
        )
        response.status_code = 404
        return response

    app.include_router(pages.router)
    app.include_router(auth.router)
    app.include_router(listings.router)
    app.include_router(seller.router)
    app.include_router(nda.router)
    app.include_router(offers.router)
    app.include_router(buyer.router)
    app.include_router(messages.router)
    app.include_router(dashboard.router)

    @app.get("/healthz", response_class=JSONResponse, tags=["ops"])
    async def healthz():
        from app.database import gateway_ready

        return {
            "status": "ok",
            "gateway_configured": gateway_ready(),
            "supabase_configured": config.has_supabase_credentials,
        }

    return app


def _wants_json(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        return True
    return request.url.path.startswith("/healthz")


app = create_app()

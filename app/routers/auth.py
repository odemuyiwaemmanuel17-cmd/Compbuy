"""Sign-up, sign-in, and sign-out routes backed by Supabase Auth."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError as PydanticValidationError

from app.dependencies import AuthServiceDep, CurrentUserDep, SettingsDep
from app.errors import AppError
from app.rendering import render, render_form_error, safe_next
from app.schemas.auth import LoginForm, RegisterForm
from app.session_store import (
    flash,
    is_signed_in,
    session_access_token,
    store_auth_session,
)
from app.utils.validation import field_errors

router = APIRouter(prefix="/auth", tags=["auth"])

LOGIN_TEMPLATE = "auth/login.html"
REGISTER_TEMPLATE = "auth/register.html"


@router.get("/login")
async def login_form(request: Request, settings: SettingsDep, next: str = ""):
    if is_signed_in(request):
        return RedirectResponse("/dashboard", status_code=303)
    return render(request, LOGIN_TEMPLATE, {"settings": settings, "next": next, "form": {}})


@router.post("/login")
async def login_submit(
    request: Request,
    settings: SettingsDep,
    auth: AuthServiceDep,
    next: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
):
    try:
        form = LoginForm(email=email, password=password)
    except PydanticValidationError as exc:
        return render_form_error(
            request,
            LOGIN_TEMPLATE,
            {"settings": settings, "next": next, "form": {"email": email}},
            message="Check the highlighted fields and try again.",
            field_errors=field_errors(exc),
        )

    try:
        session = await auth.sign_in(form.email, form.password)
    except AppError as exc:
        return render_form_error(
            request,
            LOGIN_TEMPLATE,
            {"settings": settings, "next": next, "form": {"email": form.email}},
            message=exc.message,
            field_errors=exc.field_errors or {"password": [exc.message]},
        )

    store_auth_session(request, session)
    flash(request, f"Welcome back, {session.user.email.split('@')[0]}.", category="success")
    return RedirectResponse(safe_next(next), status_code=303)


@router.get("/register")
async def register_form(request: Request, settings: SettingsDep, next: str = ""):
    if is_signed_in(request):
        return RedirectResponse("/dashboard", status_code=303)
    return render(request, REGISTER_TEMPLATE, {"settings": settings, "next": next, "form": {}})


@router.post("/register")
async def register_submit(
    request: Request,
    settings: SettingsDep,
    auth: AuthServiceDep,
    next: str = Form(""),
    email: str = Form(""),
    display_name: str = Form(""),
    password: str = Form(""),
    password_confirm: str = Form(""),
):
    context = {
        "settings": settings,
        "next": next,
        "form": {"email": email, "display_name": display_name},
    }
    errors: dict[str, list[str]] = {}
    if password != password_confirm:
        errors["password_confirm"] = ["Both passwords must match."]
    if errors:
        return render_form_error(
            request,
            REGISTER_TEMPLATE,
            context,
            message="Please correct the highlighted fields.",
            field_errors=errors,
        )

    try:
        form = RegisterForm(
            email=email, password=password, password_confirm=password_confirm, display_name=display_name
        )
    except PydanticValidationError as exc:
        return render_form_error(
            request,
            REGISTER_TEMPLATE,
            context,
            message="Please correct the highlighted fields.",
            field_errors=field_errors(exc),
        )

    try:
        session = await auth.register(form.email, form.password, form.display_name)
    except AppError as exc:
        return render_form_error(
            request,
            REGISTER_TEMPLATE,
            context,
            message=exc.message,
            field_errors=exc.field_errors,
        )

    store_auth_session(request, session)
    flash(request, "Your account is ready. Publish your first listing to start selling.", category="success")
    return RedirectResponse(safe_next(next) if next else "/listings/new", status_code=303)


@router.post("/logout")
async def logout(
    request: Request,
    auth: AuthServiceDep,
    user: CurrentUserDep,
    settings: SettingsDep,
):
    await auth.sign_out(session_access_token(request))
    request.session.clear()
    flash(request, "You have been signed out.", category="info")
    return RedirectResponse("/", status_code=303)

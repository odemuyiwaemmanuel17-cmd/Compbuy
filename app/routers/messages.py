"""Negotiation message threads."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError as PydanticValidationError

from app.dependencies import CurrentUserDep, MessageServiceDep, SettingsDep
from app.rendering import render
from app.schemas.message import MessageCreate
from app.session_store import flash

router = APIRouter(prefix="/messages", tags=["messages"])


@router.get("")
async def thread_list(
    request: Request,
    settings: SettingsDep,
    user: CurrentUserDep,
    messages: MessageServiceDep,
):
    conversations = await messages.conversations_for(user.id)
    enriched = await messages.attach_listing_titles(conversations)
    return render(
        request,
        "messages/list.html",
        {
            "settings": settings,
            "current_user": user,
            "conversations": enriched,
            "page_title": "Messages",
        },
    )


@router.get("/{conversation_id}")
async def thread(
    request: Request,
    settings: SettingsDep,
    conversation_id: str,
    user: CurrentUserDep,
    messages: MessageServiceDep,
):
    conversation = await messages.get_for_user(conversation_id, user.id)
    entries = await messages.messages_for(conversation.id, user.id)
    return render(
        request,
        "messages/thread.html",
        {
            "settings": settings,
            "current_user": user,
            "conversation": conversation,
            "messages": entries,
            "page_title": "Messages",
        },
    )


@router.post("/{conversation_id}/reply")
async def reply(
    request: Request,
    conversation_id: str,
    user: CurrentUserDep,
    messages: MessageServiceDep,
    body: str = Form(""),
):
    back = RedirectResponse(f"/messages/{conversation_id}", status_code=303)
    try:
        data = MessageCreate.model_validate({"body": body})
    except PydanticValidationError:
        flash(request, "Write a message before sending.", category="error")
        return back

    await messages.post(conversation_id, user.id, data.body)

    flash(request, "Message sent.", category="success")
    return back

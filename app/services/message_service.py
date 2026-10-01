"""Buyer/seller negotiation threads.

A conversation is created alongside the first offer on a listing and is only
ever readable by its two participants.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.database import run_query
from app.errors import NotFoundError, PermissionDeniedError
from app.models.listing import Listing
from app.models.message import Conversation, Message
from app.services.base import BaseService

CONVERSATION_COLUMNS = "id, listing_id, buyer_id, seller_id, created_at"
MESSAGE_COLUMNS = "id, conversation_id, sender_id, body, created_at"
MAX_MESSAGES_PER_THREAD = 200


class MessageService(BaseService):
    # ------------------------------------------------------------ conversations

    async def find_between(self, listing_id: str, buyer_id: str) -> Conversation | None:
        result = await run_query(
            self.gateway.table("conversations")
            .select(CONVERSATION_COLUMNS)
            .eq("listing_id", listing_id)
            .eq("buyer_id", buyer_id)
            .limit(1)
        )
        row = result.first
        return Conversation.from_row(row) if row else None

    async def open_or_get(self, listing: Listing, buyer_id: str) -> Conversation:
        """Return the thread for this buyer/listing pair, creating it on demand."""
        existing = await self.find_between(listing.id, buyer_id)
        if existing is not None:
            return existing
        created = await run_query(
            self.gateway.table("conversations").insert(
                {
                    "listing_id": listing.id,
                    "buyer_id": buyer_id,
                    "seller_id": listing.seller_id,
                }
            )
        )
        row = created.first
        if row is None:
            raise NotFoundError("We could not open a conversation for this listing.")
        return Conversation.from_row(row)

    async def get_for_user(self, conversation_id: str, user_id: str) -> Conversation:
        result = await run_query(
            self.gateway.table("conversations")
            .select(CONVERSATION_COLUMNS)
            .eq("id", conversation_id)
            .limit(1)
        )
        row = result.first
        if row is None:
            raise NotFoundError("That conversation does not exist.")
        conversation = Conversation.from_row(row)
        if not conversation.includes(user_id):
            raise PermissionDeniedError("You are not a participant in this conversation.")
        return conversation

    async def conversations_for(self, user_id: str) -> list[Conversation]:
        """Threads where the user is buyer or seller.

        Issued as two single-column filters rather than a composite ``or`` so
        the query shape stays portable across Supabase versions.
        """
        as_buyer = await run_query(
            self.gateway.table("conversations")
            .select(CONVERSATION_COLUMNS)
            .eq("buyer_id", user_id)
        )
        as_seller = await run_query(
            self.gateway.table("conversations")
            .select(CONVERSATION_COLUMNS)
            .eq("seller_id", user_id)
        )
        merged: dict[str, Conversation] = {}
        for row in [*as_buyer.rows, *as_seller.rows]:
            conversation = Conversation.from_row(row)
            if conversation.id:
                merged.setdefault(conversation.id, conversation)
        return sorted(
            merged.values(),
            key=lambda item: item.created_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

    async def attach_listing_titles(self, conversations: list[Conversation]) -> list[Conversation]:
        """Enrich threads with the listing title and latest message preview."""
        if not conversations:
            return []
        listing_ids = sorted({item.listing_id for item in conversations if item.listing_id})
        titles: dict[str, str] = {}
        if listing_ids:
            result = await run_query(
                self.gateway.table("listings")
                .select("id, title, status")
                .in_("id", listing_ids)
            )
            titles = {str(row["id"]): str(row.get("title") or "") for row in result.rows}

        thread_ids = [item.id for item in conversations]
        message_result = await run_query(
            self.gateway.table("messages")
            .select(MESSAGE_COLUMNS)
            .in_("conversation_id", thread_ids)
            .order("created_at", descending=False)
        )
        # Ascending order means the last row seen per thread is the newest.
        latest_by_thread: dict[str, Message] = {}
        for row in message_result.rows:
            message = Message.from_row(row)
            latest_by_thread[message.conversation_id] = message

        enriched: list[Conversation] = []
        for conversation in conversations:
            last = latest_by_thread.get(conversation.id)
            enriched.append(
                Conversation(
                    id=conversation.id,
                    listing_id=conversation.listing_id,
                    buyer_id=conversation.buyer_id,
                    seller_id=conversation.seller_id,
                    created_at=conversation.created_at,
                    listing_title=titles.get(conversation.listing_id, ""),
                    last_message_body=last.body if last else "",
                    last_message_at=last.created_at if last else conversation.created_at,
                    message_count=conversation.message_count,
                )
            )
        return enriched

    # ---------------------------------------------------------------- messages

    async def messages_for(self, conversation_id: str, user_id: str) -> list[Message]:
        await self.get_for_user(conversation_id, user_id)
        result = await run_query(
            self.gateway.table("messages")
            .select(MESSAGE_COLUMNS)
            .eq("conversation_id", conversation_id)
            .order("created_at", descending=False)
            .limit(MAX_MESSAGES_PER_THREAD)
        )
        return [Message.from_row(row) for row in result.rows]

    async def post(self, conversation_id: str, sender_id: str, body: str) -> Message:
        await self.get_for_user(conversation_id, sender_id)
        result = await run_query(
            self.gateway.table("messages").insert(
                {"conversation_id": conversation_id, "sender_id": sender_id, "body": body}
            )
        )
        row = result.first
        if row is None:
            raise NotFoundError("We could not send that message.")
        return Message.from_row(row)

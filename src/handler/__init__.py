import asyncio
import logging

from cachetools import TTLCache
from sqlmodel.ext.asyncio.session import AsyncSession
from voyageai.client_async import AsyncClient

from config import Settings
from handler.router import Router
from handler.whatsapp_group_link_spam import WhatsappGroupLinkSpamHandler
from handler.kb_qa import KBQAHandler
from handler.trip_album import TripAlbumHandler, TripPhotoHandler
from handler.welcome import WelcomeHandler
from models import (
    WhatsAppWebhookPayload,
)
from whatsapp import WhatsAppClient
from .base_handler import BaseHandler
from models import Message, OptOut

logger = logging.getLogger(__name__)

# In-memory processing guard: 4 minutes TTL to prevent duplicate handling
_processing_cache = TTLCache(maxsize=1000, ttl=4 * 60)
_processing_lock = asyncio.Lock()


class MessageHandler(BaseHandler):
    def __init__(
        self,
        session: AsyncSession,
        whatsapp: WhatsAppClient,
        embedding_client: AsyncClient,
        settings: Settings,
    ):
        self.router = Router(session, whatsapp, embedding_client, settings)
        self.whatsapp_group_link_spam = WhatsappGroupLinkSpamHandler(
            session, whatsapp, embedding_client, settings
        )
        self.kb_qa_handler = KBQAHandler(session, whatsapp, embedding_client, settings)
        self.trip_album_handler = TripAlbumHandler(
            session, whatsapp, embedding_client, settings
        )
        self.trip_photo_handler = TripPhotoHandler(
            session, whatsapp, embedding_client, settings
        )
        self.welcome_handler = WelcomeHandler(
            session, whatsapp, embedding_client, settings
        )
        self.settings = settings
        super().__init__(session, whatsapp, embedding_client)

    async def __call__(self, payload: WhatsAppWebhookPayload):
        message = await self.store_message(payload)

        if not message:
            return

        # Ignore messages sent by the bot itself
        my_jid = await self.whatsapp.get_my_jid()
        if message.sender_jid == my_jid.normalize_str():
            return

        # Debug: Log media info
        if payload.image or payload.video:
            logger.info(
                f"Media message received: image={payload.image}, video={payload.video}, "
                f"media_url={message.media_url}, group_jid={message.group_jid}"
            )

        # Handle photo uploads to trip albums (even without text)
        if message.media_url and message.group_jid:
            logger.info(f"Processing photo upload for group {message.group_jid}")
            # Run photo upload in background to not block other processing
            asyncio.create_task(self._handle_trip_photo(message))

        # For text-based commands, we need text
        if not message.text:
            return

        if message.sender_jid.endswith("@lid"):
            logging.info(
                f"Received message from {message.sender_jid}: {payload.model_dump_json()}"
            )

        # direct message
        if message and not message.group:
            command = message.text.strip().lower()
            if command == "opt-out":
                await self.handle_opt_out(message)
                return
            elif command == "opt-in":
                await self.handle_opt_in(message)
                return
            elif command == "status":
                await self.handle_opt_status(message)
                return
            # if autoreply is enabled, send autoreply
            elif self.settings.dm_autoreply_enabled:
                await self.send_message(
                    message.sender_jid,
                    self.settings.dm_autoreply_message,
                    message.message_id,
                )
            return

        # In-memory dedupe: if this message is already being processed/recently processed, skip
        if message and message.message_id:
            async with _processing_lock:
                if message.message_id in _processing_cache:
                    logging.info(
                        f"Message {message.message_id} already in processing cache; skipping."
                    )
                    return
                _processing_cache[message.message_id] = True

        # Check for /kb_qa command (super admin only)
        # This does not have to be a managed group
        if message.group and message.text.startswith("/kb_qa "):
            if message.chat_jid not in self.settings.qa_test_groups:
                logger.warning(
                    f"QA command attempted from non-whitelisted group: {message.chat_jid}"
                )
                return  # Silent failure
            # Check if sender is a QA tester
            if message.sender_jid not in self.settings.qa_testers:
                logger.warning(f"Unauthorized /kb_qa attempt from {message.sender_jid}")
                return  # Silent failure

            await self.kb_qa_handler(message)
            return

        # Check for /setup_trip_album command
        if message.group and message.text.strip().lower() == "/setup_trip_album":
            await self.trip_album_handler.handle_setup_command(message)
            return

        # ignore messages from unmanaged groups
        if message and message.group and not message.group.managed:
            return

        # Send welcome message for new managed groups
        if message.group and message.group.managed:
            await self.welcome_handler.send_welcome_if_new(message)

        mentioned = message.has_mentioned(my_jid)
        if mentioned:
            # Check if this is a destination setting message (if no destination set yet)
            if message.group and not message.group.destination_country:
                destination_set = await self.welcome_handler.handle_set_destination(message)
                if destination_set:
                    return  # Destination was set, no need to route further
            
            await self.router(message)
            return

        if (
            message.group
            and message.group.notify_on_spam
            and "https://chat.whatsapp.com/" in message.text
        ):
            await self.whatsapp_group_link_spam(message)
            return

    async def handle_opt_out(self, message: Message):
        opt_out = await self.session.get(OptOut, message.sender_jid)
        if not opt_out:
            opt_out = OptOut(jid=message.sender_jid)
            await self.upsert(opt_out)
            await self.send_message(
                message.chat_jid,
                "You have been opted out. You will no longer be tagged in summaries and answers.",
            )
        else:
            await self.send_message(
                message.chat_jid,
                "You are already opted out.",
            )

    async def handle_opt_in(self, message: Message):
        opt_out = await self.session.get(OptOut, message.sender_jid)
        if opt_out:
            await self.session.delete(opt_out)
            await self.session.commit()
            await self.send_message(
                message.chat_jid,
                "You have been opted in. You will now be tagged in summaries and answers.",
            )
        else:
            await self.send_message(
                message.chat_jid,
                "You are already opted in.",
            )

    async def handle_opt_status(self, message: Message):
        opt_out = await self.session.get(OptOut, message.sender_jid)
        status = "opted out" if opt_out else "opted in"
        await self.send_message(
            message.chat_jid,
            f"You are currently {status}.",
        )

    async def _handle_trip_photo(self, message: Message) -> None:
        """Handle uploading a photo to the trip album in the background."""
        try:
            await self.trip_photo_handler(message)
        except Exception as e:
            logger.error(f"Failed to upload trip photo: {e}")

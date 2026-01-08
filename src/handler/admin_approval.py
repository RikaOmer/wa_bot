"""Handler for admin approval flow when bot is added to new groups."""

import logging
import re

from sqlmodel.ext.asyncio.session import AsyncSession
from voyageai.client_async import AsyncClient

from config import Settings
from models import Group, Message
from whatsapp import WhatsAppClient
from .base_handler import BaseHandler

logger = logging.getLogger(__name__)


class AdminApprovalHandler(BaseHandler):
    """Handles admin approval flow for new groups."""

    def __init__(
        self,
        session: AsyncSession,
        whatsapp: WhatsAppClient,
        embedding_client: AsyncClient,
        settings: Settings,
    ):
        self.settings = settings
        super().__init__(session, whatsapp, embedding_client)

    async def notify_admin_new_group(
        self,
        group: Group,
        added_by_jid: str,
        added_by_name: str | None = None,
    ) -> None:
        """Send approval request to admin when bot is added to a new group."""
        if not self.settings.admin_user:
            logger.warning("No admin_user configured, cannot send approval request")
            return

        sender_display = added_by_name or added_by_jid
        group_name = group.group_name or group.group_jid

        approval_message = (
            f"🆕 *Bot added to new group*\n\n"
            f"📱 *Group:* {group_name}\n"
            f"👤 *Added by:* {sender_display}\n"
            f"🔑 *Group JID:* `{group.group_jid}`\n\n"
            f"Reply *enable* to activate the bot\n"
            f"Reply *disable* to keep it disabled"
        )

        await self.send_message(self.settings.admin_user, approval_message)
        logger.info(f"Sent approval request to admin for group {group.group_jid}")

    async def handle_admin_reply(self, message: Message) -> bool:
        """
        Handle admin's reply to approve/reject a group.
        Returns True if this was an admin approval command, False otherwise.
        """
        if not self.settings.admin_user:
            return False

        # Check if message is from admin
        if message.sender_jid != self.settings.admin_user:
            return False

        # Check if this is a reply to a bot message
        if not message.reply_to_id:
            return False

        text = message.text.strip().lower()
        if text not in ("enable", "disable"):
            return False

        # Get the original message to find the group JID
        original_message = await self.session.get(Message, message.reply_to_id)
        if not original_message or not original_message.text:
            return False

        # Check if this is a group approval message
        if "Bot added to new group" not in original_message.text:
            return False

        # Extract group JID from the original message
        jid_match = re.search(r"Group JID:\*?\s*`?([^`\n]+)`?", original_message.text)
        if not jid_match:
            await self.send_message(
                message.chat_jid, "❌ Could not find group JID in the original message."
            )
            return True

        group_jid = jid_match.group(1).strip()
        group = await self.session.get(Group, group_jid)

        if not group:
            await self.send_message(message.chat_jid, f"❌ Group not found: {group_jid}")
            return True

        if text == "enable":
            group.managed = True
            group.pending_approval = False
            await self.session.commit()
            await self.send_message(
                message.chat_jid,
                f"✅ Bot *enabled* for group: {group.group_name or group_jid}",
            )
            # Send welcome to the group
            await self.send_message(
                group_jid,
                "👋 שלום! הבוט הופעל בקבוצה זו. תייגו אותי לעזרה!",
            )
            logger.info(f"Admin enabled bot for group {group_jid}")
        else:
            group.managed = False
            group.pending_approval = False
            await self.session.commit()
            await self.send_message(
                message.chat_jid,
                f"🔴 Bot *disabled* for group: {group.group_name or group_jid}",
            )
            logger.info(f"Admin disabled bot for group {group_jid}")

        return True


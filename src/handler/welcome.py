"""Handler for welcome messages when bot joins a new group."""

import logging
from typing import Optional

from sqlmodel.ext.asyncio.session import AsyncSession
from voyageai.client_async import AsyncClient

from config import Settings
from models import Group, Message
from utils.country_detector import detect_country, detect_country_from_message, CountryInfo
from whatsapp import WhatsAppClient
from .base_handler import BaseHandler

logger = logging.getLogger(__name__)


class WelcomeHandler(BaseHandler):
    """Handles welcome messages for new groups and destination setting."""

    def __init__(
        self,
        session: AsyncSession,
        whatsapp: WhatsAppClient,
        embedding_client: AsyncClient,
        settings: Settings,
    ):
        super().__init__(session, whatsapp, embedding_client)
        self.settings = settings

    async def send_welcome_if_new(self, message: Message) -> bool:
        """
        Send a welcome message if this is a new group that hasn't been welcomed yet.
        
        Args:
            message: The incoming message that triggered this check
            
        Returns:
            True if a welcome was sent, False otherwise
        """
        if not message.group:
            return False
        
        group = message.group
        
        # Check if already welcomed
        if group.welcomed:
            return False
        
        logger.info(f"New group detected: {group.group_jid}, sending welcome message")
        
        # Try to detect country from group name
        country_info = None
        if group.group_name:
            country_info = detect_country(group.group_name)
        
        # Send appropriate welcome message
        if country_info:
            await self._send_welcome_with_country(message.chat_jid, group, country_info)
        else:
            await self._send_welcome_without_country(message.chat_jid, group)
        
        # Mark group as welcomed
        group.welcomed = True
        if country_info:
            group.destination_country = country_info.name_hebrew
        
        await self.session.commit()
        
        return True

    async def handle_set_destination(self, message: Message) -> bool:
        """
        Handle a message that sets the trip destination.
        
        Looks for messages like "אנחנו טסים לתאילנד" or "we're going to Japan"
        
        Args:
            message: The message that might contain destination info
            
        Returns:
            True if destination was set, False otherwise
        """
        if not message.group or not message.text:
            return False
        
        # Check if group already has a destination
        if message.group.destination_country:
            return False
        
        # Try to detect country from message
        country_info = detect_country_from_message(message.text)
        
        if not country_info:
            return False
        
        logger.info(f"Destination detected from message: {country_info.name_hebrew}")
        
        # Update group with destination
        message.group.destination_country = country_info.name_hebrew
        await self.session.commit()
        
        # Send confirmation message
        await self.send_message(
            message.chat_jid,
            f"מעולה! {country_info.emoji} עדכנתי את היעד ל{country_info.name_hebrew}.\n"
            f"אשמח לעזור עם כל שאלה על הטיול! 🙌"
        )
        
        return True

    async def _send_welcome_with_country(
        self, 
        chat_jid: str, 
        group: Group, 
        country_info: CountryInfo
    ) -> None:
        """Send a welcome message when country is detected from group name."""
        welcome_message = (
            f"היי כולם! 👋 אני בוטיול, אני רואה שאנחנו טסים ל{country_info.name_hebrew}! "
            f"{country_info.emoji} איזה כיף!\n\n"
            f"מה אני יכול לעשות?\n"
            f"• לסכם את השיחה - תייגו אותי ותשאלו \"מה פספסתי?\"\n"
            f"• לענות על שאלות - תייגו אותי ותשאלו כל שאלה על הטיול\n"
            f"• לעקוב אחרי הוצאות - תייגו אותי עם \"שילמתי X שקל על Y\"\n\n"
            f"פשוט תייגו אותי עם @ ואני אעזור! 🙌"
        )
        
        await self.send_message(chat_jid, welcome_message)

    async def _send_welcome_without_country(
        self, 
        chat_jid: str, 
        group: Group
    ) -> None:
        """Send a welcome message when country is not detected."""
        welcome_message = (
            f"היי כולם! 👋 אני בוטיול, שמח להצטרף לקבוצה!\n\n"
            f"לאן טסים? 🌍 תייגו אותי ותכתבו את היעד "
            f"(למשל: \"@בוטיול אנחנו טסים לתאילנד\")\n\n"
            f"מה אני יכול לעשות?\n"
            f"• לסכם את השיחה - תייגו אותי ותשאלו \"מה פספסתי?\"\n"
            f"• לענות על שאלות - תייגו אותי ותשאלו כל שאלה על הטיול\n"
            f"• לעקוב אחרי הוצאות - תייגו אותי עם \"שילמתי X שקל על Y\"\n\n"
            f"פשוט תייגו אותי עם @ ואני אעזור! 🙌"
        )
        
        await self.send_message(chat_jid, welcome_message)


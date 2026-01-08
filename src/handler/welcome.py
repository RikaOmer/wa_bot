"""Handler for welcome messages when bot joins a new group."""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlmodel.ext.asyncio.session import AsyncSession
from voyageai.client_async import AsyncClient

from config import Settings
from models import Group, Message
from utils.trip_info_extractor import extract_trip_info, TripInfo
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

        # Extract trip info from group name using OpenAI
        trip_info: Optional[TripInfo] = None
        if group.group_name:
            try:
                trip_info = await extract_trip_info(
                    group.group_name, model_name=self.settings.model_name
                )
            except Exception as e:
                logger.warning(f"Failed to extract trip info: {e}")
                trip_info = TripInfo()

        # Send appropriate welcome message
        if trip_info and trip_info.destination:
            await self._send_welcome_with_trip_info(message.chat_jid, group, trip_info)
        else:
            await self._send_welcome_without_country(message.chat_jid, group)

        # Update group with extracted info
        group.welcomed = True
        if trip_info:
            if trip_info.destination:
                group.destination_country = trip_info.destination
            if trip_info.start_date:
                group.trip_start_date = datetime.combine(
                    trip_info.start_date, datetime.min.time(), tzinfo=timezone.utc
                )
            if trip_info.end_date:
                group.trip_end_date = datetime.combine(
                    trip_info.end_date, datetime.min.time(), tzinfo=timezone.utc
                )
            if trip_info.context:
                group.trip_context = trip_info.context

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

        # Try to extract trip info from message
        try:
            trip_info = await extract_trip_info(
                message.text, model_name=self.settings.model_name
            )
        except Exception as e:
            logger.warning(f"Failed to extract trip info from message: {e}")
            return False

        if not trip_info or not trip_info.destination:
            return False

        logger.info(f"Destination detected from message: {trip_info.destination}")

        # Update group with destination
        message.group.destination_country = trip_info.destination
        if trip_info.start_date:
            message.group.trip_start_date = datetime.combine(
                trip_info.start_date, datetime.min.time(), tzinfo=timezone.utc
            )
        if trip_info.end_date:
            message.group.trip_end_date = datetime.combine(
                trip_info.end_date, datetime.min.time(), tzinfo=timezone.utc
            )
        if trip_info.context:
            message.group.trip_context = trip_info.context

        await self.session.commit()

        # Send confirmation message
        emoji = trip_info.destination_emoji or "✈️"
        await self.send_message(
            message.chat_jid,
            f"מעולה! {emoji} עדכנתי את היעד ל{trip_info.destination}.\n"
            f"אשמח לעזור עם כל שאלה על הטיול! 🙌",
        )

        return True

    async def _send_welcome_with_trip_info(
        self, chat_jid: str, group: Group, trip_info: TripInfo
    ) -> None:
        """Send a welcome message when trip info is extracted from group name."""
        emoji = trip_info.destination_emoji or "✈️"

        # Build context line if we have extra info
        context_parts = []
        if trip_info.context:
            context_parts.append(trip_info.context)
        if trip_info.start_date and trip_info.end_date:
            context_parts.append(
                f"{trip_info.start_date.strftime('%d.%m')}-{trip_info.end_date.strftime('%d.%m')}"
            )
        elif trip_info.start_date:
            context_parts.append(f"מתאריך {trip_info.start_date.strftime('%d.%m')}")

        context_line = ""
        if context_parts:
            context_line = f"\n{' • '.join(context_parts)}\n"

        welcome_message = (
            f"היי כולם! 👋 אני בוטיול, אני רואה שאנחנו טסים ל{trip_info.destination}! "
            f"{emoji} איזה כיף!{context_line}\n"
            f"🎯 *מה אני יכול לעשות?*\n\n"
            f"📝 *סיכום ושאלות*\n"
            f"• \"מה פספסתי?\" - סיכום השיחה של היום\n"
            f"• שאלות על מה שדיברתם - אני זוכר הכל!\n\n"
            f"📍 *מקומות והמלצות*\n"
            f"• \"ספר לי על מסעדת X\" - מידע על מקומות\n"
            f"• \"תמליץ על מסעדה\" - המלצות מותאמות אישית\n\n"
            f"📅 *תכנון הטיול*\n"
            f"• \"מה התוכניות?\" - אירועים ולוח זמנים\n"
            f"• \"כמה ימים עד הטיסה?\" - ספירה לאחור\n"
            f"• \"לוח זמנים\" - צפייה בתוכנית הטיול\n\n"
            f"💰 *הוצאות*\n"
            f"• \"שילמתי 50 שקל על פיצה\" - מעקב הוצאות\n"
            f"• \"כמה כל אחד חייב?\" - מאזן הוצאות\n\n"
            f"🎒 *עוד כלים*\n"
            f"• \"מה לארוז?\" - רשימת ציוד חכמה\n"
            f"• \"הצבעה: X או Y\" - יצירת הצבעה\n\n"
            f"💡 תייגו אותי עם @ ואני אעזור!\n"
            f"לרשימת כל הפיצ'רים: \"מה אתה יודע לעשות?\""
        )

        await self.send_message(chat_jid, welcome_message)

    async def _send_welcome_without_country(
        self, chat_jid: str, group: Group
    ) -> None:
        """Send a welcome message when country is not detected."""
        welcome_message = (
            f"היי כולם! 👋 אני בוטיול, שמח להצטרף לקבוצה!\n\n"
            f"🌍 לאן טסים? תייגו אותי ותכתבו את היעד "
            f"(למשל: \"@בוטיול אנחנו טסים לתאילנד\")\n\n"
            f"🎯 *מה אני יכול לעשות?*\n\n"
            f"📝 *סיכום ושאלות*\n"
            f"• \"מה פספסתי?\" - סיכום השיחה של היום\n"
            f"• שאלות על מה שדיברתם - אני זוכר הכל!\n\n"
            f"📍 *מקומות והמלצות*\n"
            f"• \"ספר לי על מסעדת X\" - מידע על מקומות\n"
            f"• \"תמליץ על מסעדה\" - המלצות מותאמות אישית\n\n"
            f"📅 *תכנון הטיול*\n"
            f"• \"מה התוכניות?\" - אירועים ולוח זמנים\n"
            f"• \"כמה ימים עד הטיסה?\" - ספירה לאחור\n"
            f"• \"לוח זמנים\" - צפייה בתוכנית הטיול\n\n"
            f"💰 *הוצאות*\n"
            f"• \"שילמתי 50 שקל על פיצה\" - מעקב הוצאות\n"
            f"• \"כמה כל אחד חייב?\" - מאזן הוצאות\n\n"
            f"🎒 *עוד כלים*\n"
            f"• \"מה לארוז?\" - רשימת ציוד חכמה\n"
            f"• \"הצבעה: X או Y\" - יצירת הצבעה\n\n"
            f"💡 תייגו אותי עם @ ואני אעזור!\n"
            f"לרשימת כל הפיצ'רים: \"מה אתה יודע לעשות?\""
        )

        await self.send_message(chat_jid, welcome_message)

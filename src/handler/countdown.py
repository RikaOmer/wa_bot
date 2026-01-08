"""Handler for trip countdown feature."""

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from sqlmodel.ext.asyncio.session import AsyncSession
from voyageai.client_async import AsyncClient

from config import Settings
from models import Message
from whatsapp import WhatsAppClient
from services.prompt_manager import prompt_manager
from .base_handler import BaseHandler

logger = logging.getLogger(__name__)


class ParsedDates(BaseModel):
    """Structured date extraction from message."""
    
    has_dates: bool = Field(
        default=False,
        description="Whether the message contains trip dates"
    )
    start_date: Optional[str] = Field(
        default=None,
        description="Trip start date in ISO format (YYYY-MM-DD) if found"
    )
    end_date: Optional[str] = Field(
        default=None,
        description="Trip end date in ISO format (YYYY-MM-DD) if found"
    )
    is_query: bool = Field(
        default=False,
        description="Whether this is a query about the countdown (vs setting dates)"
    )


DATE_PARSER_PROMPT = """You are a date extraction assistant. Extract trip dates from user messages.

Examples:
- "נוסעים ב-15.3" -> start_date: 2026-03-15, is_query: false
- "הטיסה ב-15 למרץ" -> start_date: 2026-03-15, is_query: false  
- "טסים 15-22 למרץ" -> start_date: 2026-03-15, end_date: 2026-03-22, is_query: false
- "כמה זמן עד הטיסה?" -> is_query: true
- "מתי נוסעים?" -> is_query: true
- "הטיול בין 10/4 ל-20/4" -> start_date: 2026-04-10, end_date: 2026-04-20, is_query: false

Current year is {current_year}. If only day/month given, assume current or next year (whichever makes the date in the future).

Return has_dates: true if dates were found, is_query: true if asking about countdown.
Dates should be in ISO format: YYYY-MM-DD."""


class CountdownHandler(BaseHandler):
    """Handles trip countdown queries and date setting."""

    def __init__(
        self,
        session: AsyncSession,
        whatsapp: WhatsAppClient,
        embedding_client: AsyncClient,
        settings: Settings,
    ):
        super().__init__(session, whatsapp, embedding_client)
        self.settings = settings

    async def __call__(self, message: Message) -> None:
        """
        Handle a countdown-related message.
        
        Args:
            message: The incoming WhatsApp message
        """
        if not message.text or not message.group:
            return

        # Parse the message to understand intent
        parsed = await self._parse_dates(message.text)
        
        if parsed.is_query:
            # User is asking about the countdown
            await self._handle_countdown_query(message)
        elif parsed.has_dates:
            # User is setting dates
            await self._handle_set_dates(message, parsed)
        else:
            # Couldn't parse - ask for clarification
            await self._ask_for_dates(message)

    async def _parse_dates(self, text: str) -> ParsedDates:
        """Parse dates from message text using LLM."""
        current_year = datetime.now().year
        prompt = DATE_PARSER_PROMPT.format(current_year=current_year)
        
        agent = Agent(
            model=self.settings.model_name,
            system_prompt=prompt,
            output_type=ParsedDates,
        )
        
        result = await agent.run(text)
        return result.output

    async def _handle_countdown_query(self, message: Message) -> None:
        """Handle a query about the countdown to the trip."""
        group = message.group
        if not group:
            return
        
        if not group.trip_start_date:
            # No dates set yet
            destination = group.destination_country or "הטיול"
            await self.send_message(
                message.chat_jid,
                f"🤔 עדיין לא הגדרתם תאריכים ל{destination}!\n"
                f"תייגו אותי עם התאריך, למשל:\n"
                f"\"@בוטיול נוסעים ב-15 למרץ\""
            )
            return
        
        # Calculate days until trip
        now = datetime.now(timezone.utc)
        start_date = group.trip_start_date
        
        # Ensure start_date is timezone aware
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)
        
        delta = start_date - now
        days_until = delta.days
        
        destination = group.destination_country or "הטיול"
        
        if days_until < 0:
            # Trip already started or passed
            if group.trip_end_date:
                end_date = group.trip_end_date
                if end_date.tzinfo is None:
                    end_date = end_date.replace(tzinfo=timezone.utc)
                
                if now <= end_date:
                    # Currently on trip!
                    days_in = abs(days_until)
                    await self.send_message(
                        message.chat_jid,
                        f"🎉 אתם כבר ב{destination}! יום {days_in + 1} לטיול!\n"
                        f"תהנו! 🌴"
                    )
                    return
            
            # Trip has passed
            await self.send_message(
                message.chat_jid,
                f"הטיול ל{destination} כבר היה! 😊\n"
                f"איך היה? מקווה שנהניתם!"
            )
        elif days_until == 0:
            await self.send_message(
                message.chat_jid,
                f"🎊 היום יוצאים ל{destination}!\n"
                f"טיסה טובה וטיול מהנה! ✈️🌴"
            )
        elif days_until == 1:
            await self.send_message(
                message.chat_jid,
                f"😱 מחר יוצאים ל{destination}!\n"
                f"ארזתם? מוכנים? 🧳"
            )
        elif days_until <= 7:
            await self.send_message(
                message.chat_jid,
                f"⏰ עוד {days_until} ימים עד {destination}!\n"
                f"הספירה לאחור התחילה! 🎉"
            )
        elif days_until <= 30:
            weeks = days_until // 7
            remaining_days = days_until % 7
            if remaining_days == 0:
                await self.send_message(
                    message.chat_jid,
                    f"📅 עוד {weeks} שבועות בדיוק עד {destination}!\n"
                    f"הזמן טס! ✈️"
                )
            else:
                await self.send_message(
                    message.chat_jid,
                    f"📅 עוד {weeks} שבועות ו-{remaining_days} ימים עד {destination}!\n"
                    f"({days_until} ימים) 🗓️"
                )
        else:
            months = days_until // 30
            await self.send_message(
                message.chat_jid,
                f"📆 עוד כ-{months} חודשים ({days_until} ימים) עד {destination}!\n"
                f"יש זמן להתארגן 😎"
            )

    async def _handle_set_dates(self, message: Message, parsed: ParsedDates) -> None:
        """Handle setting trip dates."""
        group = message.group
        if not group:
            return
        
        try:
            if parsed.start_date:
                group.trip_start_date = datetime.fromisoformat(parsed.start_date).replace(
                    tzinfo=timezone.utc
                )
            if parsed.end_date:
                group.trip_end_date = datetime.fromisoformat(parsed.end_date).replace(
                    tzinfo=timezone.utc
                )
            
            await self.session.commit()
            
            destination = group.destination_country or "הטיול"
            
            if parsed.start_date and parsed.end_date:
                start_formatted = self._format_date_hebrew(parsed.start_date)
                end_formatted = self._format_date_hebrew(parsed.end_date)
                await self.send_message(
                    message.chat_jid,
                    f"✅ מעולה! עדכנתי את תאריכי {destination}:\n"
                    f"📅 {start_formatted} - {end_formatted}\n\n"
                    f"תייגו אותי ושאלו \"כמה זמן עד הטיסה?\" בכל עת! ⏰"
                )
            elif parsed.start_date:
                start_formatted = self._format_date_hebrew(parsed.start_date)
                await self.send_message(
                    message.chat_jid,
                    f"✅ מעולה! עדכנתי - יוצאים ל{destination} ב-{start_formatted}!\n\n"
                    f"תייגו אותי ושאלו \"כמה זמן עד הטיסה?\" בכל עת! ⏰"
                )
        except Exception as e:
            logger.error(f"Error setting dates: {e}")
            await self.send_message(
                message.chat_jid,
                "לא הצלחתי להבין את התאריך 😅\n"
                "נסו לכתוב בפורמט ברור, למשל: \"נוסעים ב-15.3.2026\""
            )

    async def _ask_for_dates(self, message: Message) -> None:
        """Ask user to provide dates in a clear format."""
        await self.send_message(
            message.chat_jid,
            "לא הצלחתי להבין 🤔\n"
            "כדי לעדכן תאריכים, כתבו משהו כמו:\n"
            "• \"נוסעים ב-15 למרץ\"\n"
            "• \"הטיול בין 10/4 ל-20/4\"\n\n"
            "או שאלו \"כמה זמן עד הטיסה?\" אם כבר הגדרתם תאריך!"
        )

    def _format_date_hebrew(self, date_str: str) -> str:
        """Format ISO date string to Hebrew-friendly format."""
        try:
            date = datetime.fromisoformat(date_str)
            months_hebrew = [
                "", "ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
                "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"
            ]
            return f"{date.day} ב{months_hebrew[date.month]} {date.year}"
        except Exception:
            return date_str


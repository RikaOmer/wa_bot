"""Handler for trip itinerary management in WhatsApp groups."""

import json
import logging
from datetime import date, datetime, timedelta
from typing import List, Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession
from voyageai.client_async import AsyncClient

from config import Settings
from models import Message, Group, KBTopic
from models.itinerary import ItineraryItem
from whatsapp import WhatsAppClient
from whatsapp.jid import normalize_jid
from .base_handler import BaseHandler

logger = logging.getLogger(__name__)


class ParsedItineraryRequest(BaseModel):
    """Parsed itinerary request."""

    action: str = Field(description="Action: view, add, generate")
    target_date: Optional[str] = Field(default=None, description="Target date (YYYY-MM-DD)")
    time_slot: Optional[str] = Field(default=None, description="Time slot")
    title: Optional[str] = Field(default=None, description="Activity title")
    location: Optional[str] = Field(default=None, description="Location")


class ItineraryHandler(BaseHandler):
    """Handles itinerary management for WhatsApp groups."""

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
        Process an itinerary-related request.

        Args:
            message: The incoming WhatsApp message
        """
        logger.info(
            f"ItineraryHandler called with message: {message.text[:50] if message.text else 'None'}..."
        )

        if not message.text:
            return

        if not message.group_jid:
            await self.send_message(
                message.chat_jid,
                "❌ ניהול לוח זמנים עובד רק בקבוצות.",
            )
            return

        # Parse the request
        parsed = await self._parse_itinerary_request(message.text)

        match parsed.action:
            case "view":
                await self._handle_view(message, parsed.target_date)
            case "add":
                await self._handle_add(message, parsed)
            case "generate":
                await self._handle_generate(message)
            case _:
                await self._handle_view(message, None)

    async def _parse_itinerary_request(self, text: str) -> ParsedItineraryRequest:
        """Parse the itinerary request using LLM."""
        agent = Agent(
            model=self.settings.model_name,
            system_prompt="""Parse the user's itinerary request.

Actions:
- "view": User wants to see the itinerary (default). Look for: "לוח זמנים", "מה התוכנית", "what's planned", "itinerary", "schedule"
- "add": User wants to add an item. Look for: "הוסף", "add", specific activity mentions with time
- "generate": User wants to auto-generate from events. Look for: "צור לוח זמנים", "generate itinerary", "build schedule"

For view:
- Extract target_date if specified (today, tomorrow, specific date, or day like "יום שלישי")

For add:
- Extract time_slot (morning/בוקר, afternoon/צהריים, evening/ערב, or HH:MM)
- Extract title (what the activity is)
- Extract location if mentioned
- Extract target_date

Today's date context will be provided by the system.""",
            output_type=ParsedItineraryRequest,
        )

        result = await agent.run(text)
        return result.output

    async def _handle_view(
        self, message: Message, target_date: Optional[str]
    ) -> None:
        """View the itinerary."""
        group = await self.session.get(Group, message.group_jid)
        
        # Determine date range
        if target_date:
            try:
                view_date = datetime.strptime(target_date, "%Y-%m-%d").date()
                start_date = view_date
                end_date = view_date
            except ValueError:
                start_date = date.today()
                end_date = start_date + timedelta(days=7)
        elif group and group.trip_start_date:
            start_date = group.trip_start_date.date()
            end_date = group.trip_end_date.date() if group.trip_end_date else start_date + timedelta(days=7)
        else:
            start_date = date.today()
            end_date = start_date + timedelta(days=7)

        # Get items
        q = (
            select(ItineraryItem)
            .where(ItineraryItem.group_jid == message.group_jid)
            .where(ItineraryItem.item_date >= start_date)
            .where(ItineraryItem.item_date <= end_date)
            .order_by(ItineraryItem.item_date, ItineraryItem.time_slot)
        )
        result = await self.session.exec(q)
        items = result.all()

        if not items:
            # Try to build from events
            events_info = await self._get_events_from_kb(message)
            if events_info:
                await self.send_message(
                    message.chat_jid,
                    f"📅 לא נמצאו פריטים בלוח הזמנים.\n\n"
                    f"אבל מצאתי {len(events_info)} אירועים בהיסטוריית השיחה.\n"
                    f"תגידו \"צור לוח זמנים\" ואני אבנה אותו מהאירועים!",
                )
            else:
                await self.send_message(
                    message.chat_jid,
                    "📅 לוח הזמנים ריק.\n\n"
                    "להוספת פריט: \"הוסף לבוקר ביום X: פעילות\"\n"
                    "או שתפו פרטי טיסות/הזמנות ואני אזכור אותם!",
                )
            return

        # Format itinerary
        current_date = None
        lines = ["📅 **לוח זמנים לטיול**\n"]

        for item in items:
            if item.item_date != current_date:
                current_date = item.item_date
                day_name = self._get_hebrew_day(current_date)
                lines.append(f"\n**{day_name} ({current_date.strftime('%d/%m')})**")

            time_emoji = self._get_time_emoji(item.time_slot)
            location_text = f" @ {item.location}" if item.location else ""
            lines.append(f"{time_emoji} {item.time_slot}: {item.title}{location_text}")

        await self.send_message(message.chat_jid, "\n".join(lines))

    async def _handle_add(
        self, message: Message, parsed: ParsedItineraryRequest
    ) -> None:
        """Add an item to the itinerary."""
        if not parsed.title:
            await self.send_message(
                message.chat_jid,
                "❌ לא הבנתי מה להוסיף.\n"
                "דוגמה: \"הוסף לבוקר מחר: סיור בעיר העתיקה\"",
            )
            return

        # Determine date
        if parsed.target_date:
            try:
                item_date = datetime.strptime(parsed.target_date, "%Y-%m-%d").date()
            except ValueError:
                item_date = date.today()
        else:
            item_date = date.today()

        # Ensure sender exists
        await self.ensure_sender_exists(message.sender_jid, message.sender.push_name if message.sender else None)

        # Create item
        item = ItineraryItem(
            group_jid=message.group_jid,
            item_date=item_date,
            time_slot=parsed.time_slot or "morning",
            title=parsed.title,
            location=parsed.location,
            created_by_jid=normalize_jid(message.sender_jid),
        )
        self.session.add(item)
        await self.session.commit()

        day_name = self._get_hebrew_day(item_date)
        await self.send_message(
            message.chat_jid,
            f"✅ נוסף ללוח הזמנים!\n"
            f"📅 {day_name} ({item_date.strftime('%d/%m')})\n"
            f"🕐 {item.time_slot}: {item.title}",
        )

    async def _handle_generate(self, message: Message) -> None:
        """Generate itinerary from KB events."""
        events_info = await self._get_events_from_kb(message)

        if not events_info:
            await self.send_message(
                message.chat_jid,
                "❌ לא מצאתי אירועים בהיסטוריית השיחה.\n"
                "שתפו פרטי טיסות, הזמנות ופעילויות ואני אזכור אותם!",
            )
            return

        # Ensure sender exists
        await self.ensure_sender_exists(message.sender_jid, message.sender.push_name if message.sender else None)

        # Create items from events
        created = 0
        for evt in events_info:
            if not evt.get("date"):
                continue

            try:
                evt_date = datetime.strptime(evt["date"], "%Y-%m-%d").date()
            except ValueError:
                continue

            # Determine time slot from event type/time
            time_slot = evt.get("time") or self._guess_time_slot(evt.get("type", ""))

            item = ItineraryItem(
                group_jid=message.group_jid,
                item_date=evt_date,
                time_slot=time_slot,
                title=evt.get("title", "Event"),
                created_by_jid=normalize_jid(message.sender_jid),
            )
            self.session.add(item)
            created += 1

        await self.session.commit()

        await self.send_message(
            message.chat_jid,
            f"✅ נוצר לוח זמנים עם {created} פריטים!\n"
            f"תגידו \"לוח זמנים\" לצפייה.",
        )

    async def _get_events_from_kb(self, message: Message) -> List[dict]:
        """Get events from KB topics."""
        events = []

        q = (
            select(KBTopic)
            .where(col(KBTopic.events).isnot(None))
            .where(KBTopic.group_jid == message.group_jid)
            .limit(30)
        )
        result = await self.session.exec(q)
        topics = result.all()

        for topic in topics:
            if not topic.events:
                continue
            try:
                events_data = json.loads(topic.events)
                events.extend(events_data)
            except json.JSONDecodeError:
                continue

        return events

    def _get_hebrew_day(self, d: date) -> str:
        """Get Hebrew day name."""
        days = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
        return f"יום {days[d.weekday()]}"

    def _get_time_emoji(self, time_slot: str) -> str:
        """Get emoji for time slot."""
        if "morning" in time_slot.lower() or "בוקר" in time_slot:
            return "🌅"
        elif "afternoon" in time_slot.lower() or "צהריים" in time_slot:
            return "☀️"
        elif "evening" in time_slot.lower() or "ערב" in time_slot:
            return "🌙"
        return "🕐"

    def _guess_time_slot(self, event_type: str) -> str:
        """Guess time slot from event type."""
        if event_type in ["flight", "hotel_checkin"]:
            return "morning"
        elif event_type == "hotel_checkout":
            return "morning"
        elif event_type in ["activity", "tour"]:
            return "afternoon"
        elif event_type == "reservation":
            return "evening"
        return "afternoon"



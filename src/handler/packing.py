"""Handler for smart packing list generation in WhatsApp groups."""

import json
import logging
from typing import List

from pydantic_ai import Agent
from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession
from voyageai.client_async import AsyncClient

from config import Settings
from models import Message, KBTopic, Group
from services.prompt_manager import prompt_manager
from whatsapp import WhatsAppClient
from .base_handler import BaseHandler

logger = logging.getLogger(__name__)


class PackingHandler(BaseHandler):
    """Handles packing list generation for WhatsApp groups."""

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
        Generate a smart packing list based on trip context.

        Args:
            message: The incoming WhatsApp message
        """
        logger.info(
            f"PackingHandler called with message: {message.text[:50] if message.text else 'None'}..."
        )

        if not message.text:
            return

        # Gather trip context
        trip_context = await self._get_trip_context(message)
        activities = await self._get_planned_activities(message)

        # Generate packing list
        response = await self._generate_packing_list(
            message.text, trip_context, activities
        )

        await self.send_message(message.chat_jid, response)

    async def _get_trip_context(self, message: Message) -> dict:
        """
        Get trip context from group settings.

        Args:
            message: The incoming message

        Returns:
            Dict with trip context
        """
        context = {
            "destination": None,
            "trip_start": None,
            "trip_end": None,
            "duration_days": None,
        }

        if message.group:
            group = await self.session.get(Group, message.group.group_jid)
            if group:
                context["destination"] = group.destination_country

                if group.trip_start_date:
                    context["trip_start"] = group.trip_start_date.strftime("%Y-%m-%d")
                    
                    if group.trip_end_date:
                        context["trip_end"] = group.trip_end_date.strftime("%Y-%m-%d")
                        duration = (group.trip_end_date - group.trip_start_date).days
                        context["duration_days"] = duration

        return context

    async def _get_planned_activities(self, message: Message) -> List[str]:
        """
        Get activities mentioned in group discussions.

        Args:
            message: The incoming message

        Returns:
            List of activity types mentioned
        """
        activities = set()

        group_jids = None
        if message.group:
            group_jids = [message.group.group_jid]

        # Search for topics with events (activities)
        q = select(KBTopic).where(col(KBTopic.events).isnot(None)).limit(20)

        if group_jids:
            q = q.where(col(KBTopic.group_jid).in_(group_jids))

        result = await self.session.exec(q)
        topics = result.all()

        for topic in topics:
            if not topic.events:
                continue

            try:
                events_data = json.loads(topic.events)
                for evt in events_data:
                    evt_type = evt.get("type", "")
                    if evt_type in ["activity", "tour"]:
                        title = evt.get("title", "").lower()
                        # Extract activity keywords
                        if any(word in title for word in ["hike", "hiking", "טיול רגלי", "הליכה"]):
                            activities.add("hiking")
                        if any(word in title for word in ["beach", "swim", "חוף", "שחייה"]):
                            activities.add("beach")
                        if any(word in title for word in ["snorkel", "dive", "צלילה"]):
                            activities.add("water_sports")
                        if any(word in title for word in ["museum", "מוזיאון", "gallery"]):
                            activities.add("cultural")
                        if any(word in title for word in ["party", "club", "מסיבה"]):
                            activities.add("nightlife")
            except json.JSONDecodeError:
                continue

        # Also check locations for activity hints
        q = select(KBTopic).where(col(KBTopic.locations).isnot(None)).limit(20)
        if group_jids:
            q = q.where(col(KBTopic.group_jid).in_(group_jids))

        result = await self.session.exec(q)
        topics = result.all()

        for topic in topics:
            if not topic.locations:
                continue

            try:
                locs_data = json.loads(topic.locations)
                for loc in locs_data:
                    loc_type = loc.get("type", "").lower()
                    if loc_type == "beach":
                        activities.add("beach")
                    elif loc_type in ["restaurant", "cafe", "bar"]:
                        activities.add("dining")
                    elif loc_type in ["museum", "gallery", "attraction"]:
                        activities.add("cultural")
            except json.JSONDecodeError:
                continue

        logger.info(f"Found activities: {activities}")
        return list(activities)

    async def _generate_packing_list(
        self,
        query: str,
        trip_context: dict,
        activities: List[str],
    ) -> str:
        """
        Generate a packing list using LLM.

        Args:
            query: The user's original query
            trip_context: Trip context information
            activities: List of planned activity types

        Returns:
            Generated packing list string
        """
        # Build context string
        context_parts = []

        if trip_context.get("destination"):
            context_parts.append(f"🌍 Destination: {trip_context['destination']}")

        if trip_context.get("duration_days"):
            context_parts.append(f"📅 Duration: {trip_context['duration_days']} days")
        elif trip_context.get("trip_start"):
            context_parts.append(f"📅 Start date: {trip_context['trip_start']}")

        if activities:
            context_parts.append(f"🎯 Planned activities: {', '.join(activities)}")

        context_text = "\n".join(context_parts) if context_parts else "No trip details available"

        agent = Agent(
            model=self.settings.model_name,
            system_prompt=prompt_manager.render(
                "packing_list.j2",
                trip_context=context_text,
                activities=activities,
            ),
            output_type=str,
        )

        result = await agent.run(query)
        return result.output


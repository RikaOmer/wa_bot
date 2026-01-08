"""Handler for event and schedule queries in WhatsApp groups."""

import json
import logging
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession
from voyageai.client_async import AsyncClient

from config import Settings
from models import Message, KBTopic
from services.prompt_manager import prompt_manager
from utils.voyage_embed_text import voyage_embed_text
from whatsapp import WhatsAppClient
from .base_handler import BaseHandler

logger = logging.getLogger(__name__)


class EventInfo(BaseModel):
    """Structured event data from KB topics."""

    title: str
    date: Optional[str]
    time: Optional[str]
    type: str
    context: str
    topic_summary: str


class EventHandler(BaseHandler):
    """Handles event and schedule-related queries in WhatsApp groups."""

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
        Process an event-related query.

        Args:
            message: The incoming WhatsApp message
        """
        logger.info(
            f"EventHandler called with message: {message.text[:50] if message.text else 'None'}..."
        )

        if not message.text:
            return

        # Search for events in the knowledge base
        events = await self._search_events(message)

        if events:
            # Generate response with event information
            response = await self._generate_event_response(message.text, events)
        else:
            # No events found
            response = await self._generate_no_events_response(message.text)

        await self.send_message(message.chat_jid, response)

    async def _search_events(self, message: Message) -> List[EventInfo]:
        """
        Search the knowledge base for events matching the user's query.

        Args:
            message: The incoming message

        Returns:
            List of EventInfo objects found in KB
        """
        # Get query embedding for semantic search
        query_embedding = (
            await voyage_embed_text(self.embedding_client, [message.text])
        )[0]

        # Determine which groups to search
        group_jids = None
        if message.group:
            group_jids = [message.group.group_jid]
            if message.group.community_keys:
                related_groups = await message.group.get_related_community_groups(
                    self.session
                )
                group_jids.extend([g.group_jid for g in related_groups])

        # Search for topics with events using vector similarity
        q = (
            select(KBTopic)
            .where(col(KBTopic.events).isnot(None))
            .order_by(KBTopic.embedding.cosine_distance(query_embedding))
            .limit(15)
        )

        if group_jids:
            q = q.where(col(KBTopic.group_jid).in_(group_jids))

        result = await self.session.exec(q)
        topics = result.all()

        # Extract and deduplicate events
        found_events: List[EventInfo] = []
        seen_titles: set[str] = set()

        for topic in topics:
            if not topic.events:
                continue

            try:
                events_data = json.loads(topic.events)
                for evt in events_data:
                    evt_title = evt.get("title", "").lower()
                    # Skip duplicates
                    if evt_title in seen_titles:
                        continue
                    seen_titles.add(evt_title)

                    found_events.append(
                        EventInfo(
                            title=evt.get("title", "Unknown"),
                            date=evt.get("date"),
                            time=evt.get("time"),
                            type=evt.get("type", "event"),
                            context=evt.get("context", "mentioned"),
                            topic_summary=topic.summary,
                        )
                    )
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse events JSON for topic {topic.id}")
                continue

        # Sort events by date (if available)
        found_events.sort(
            key=lambda e: (e.date or "9999-99-99", e.time or "99:99")
        )

        logger.info(f"Found {len(found_events)} events matching query")
        return found_events[:10]  # Limit to top 10 events

    async def _generate_event_response(
        self, query: str, events: List[EventInfo]
    ) -> str:
        """
        Generate a response about events using LLM.

        Args:
            query: The user's original query
            events: List of events found in KB

        Returns:
            Generated response string
        """
        # Format events for the prompt
        event_context = "\n\n".join(
            [
                f"📅 **{evt.title}**\n"
                f"- Type: {evt.type}\n"
                f"- Date: {evt.date or 'Not specified'}\n"
                f"- Time: {evt.time or 'Not specified'}\n"
                f"- Status: {evt.context}\n"
                f"- Context: {evt.topic_summary}"
                for evt in events
            ]
        )

        agent = Agent(
            model=self.settings.model_name,
            system_prompt=prompt_manager.render(
                "event_rag.j2", event_context=event_context
            ),
            output_type=str,
        )

        result = await agent.run(query)
        return result.output

    async def _generate_no_events_response(self, query: str) -> str:
        """
        Generate a helpful response when no events are found.

        Args:
            query: The user's original query

        Returns:
            Friendly response indicating no events found
        """
        agent = Agent(
            model=self.settings.model_name,
            system_prompt="""You are a helpful travel assistant. The user asked about events or plans, but you couldn't find any in the group's discussion history.

Respond in a friendly, helpful way:
1. Acknowledge you couldn't find specific events/plans in the group history
2. Suggest they share flight details, reservations, or plans in the group
3. Mention you'll remember them for future reference
4. Keep it short (2-3 sentences)

Respond in the same language as the query (Hebrew or English).""",
            output_type=str,
        )

        result = await agent.run(query)
        return result.output


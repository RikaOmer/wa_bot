"""Handler for personalized recommendations in WhatsApp groups."""

import json
import logging
from typing import List, Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession
from voyageai.client_async import AsyncClient

from config import Settings
from models import Message, KBTopic, Group
from services.prompt_manager import prompt_manager
from utils.voyage_embed_text import voyage_embed_text
from whatsapp import WhatsAppClient
from .base_handler import BaseHandler

logger = logging.getLogger(__name__)


class PreferenceInfo(BaseModel):
    """Structured preference data from KB topics."""

    category: str
    preference: str
    sentiment: str
    mentioned_by: str


class LocationContext(BaseModel):
    """Location with its context from discussions."""

    name: str
    type: str
    context: str
    topic_summary: str


class RecommendationHandler(BaseHandler):
    """Handles recommendation requests in WhatsApp groups."""

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
        Process a recommendation request.

        Args:
            message: The incoming WhatsApp message
        """
        logger.info(
            f"RecommendationHandler called with message: {message.text[:50] if message.text else 'None'}..."
        )

        if not message.text:
            return

        # Gather context: preferences, locations, and group info
        preferences = await self._get_group_preferences(message)
        locations = await self._get_relevant_locations(message)
        group_context = await self._get_group_context(message)

        # Generate personalized recommendation
        response = await self._generate_recommendation(
            message.text, preferences, locations, group_context
        )

        await self.send_message(message.chat_jid, response)

    async def _get_group_preferences(self, message: Message) -> List[PreferenceInfo]:
        """
        Get preferences expressed by group members.

        Args:
            message: The incoming message

        Returns:
            List of PreferenceInfo objects
        """
        group_jids = None
        if message.group:
            group_jids = [message.group.group_jid]

        # Search for topics with preferences
        q = (
            select(KBTopic)
            .where(col(KBTopic.preferences).isnot(None))
            .limit(20)
        )

        if group_jids:
            q = q.where(col(KBTopic.group_jid).in_(group_jids))

        result = await self.session.exec(q)
        topics = result.all()

        # Extract preferences
        all_preferences: List[PreferenceInfo] = []
        for topic in topics:
            if not topic.preferences:
                continue

            try:
                prefs_data = json.loads(topic.preferences)
                for pref in prefs_data:
                    all_preferences.append(
                        PreferenceInfo(
                            category=pref.get("category", "general"),
                            preference=pref.get("preference", ""),
                            sentiment=pref.get("sentiment", "neutral"),
                            mentioned_by=pref.get("mentioned_by", "someone"),
                        )
                    )
            except json.JSONDecodeError:
                continue

        logger.info(f"Found {len(all_preferences)} preferences")
        return all_preferences

    async def _get_relevant_locations(self, message: Message) -> List[LocationContext]:
        """
        Get locations discussed by the group that might be relevant.

        Args:
            message: The incoming message

        Returns:
            List of LocationContext objects
        """
        # Get query embedding
        query_embedding = (
            await voyage_embed_text(self.embedding_client, [message.text])
        )[0]

        group_jids = None
        if message.group:
            group_jids = [message.group.group_jid]

        # Search for topics with locations
        q = (
            select(KBTopic)
            .where(col(KBTopic.locations).isnot(None))
            .order_by(KBTopic.embedding.cosine_distance(query_embedding))
            .limit(10)
        )

        if group_jids:
            q = q.where(col(KBTopic.group_jid).in_(group_jids))

        result = await self.session.exec(q)
        topics = result.all()

        # Extract locations
        locations: List[LocationContext] = []
        seen_names: set[str] = set()

        for topic in topics:
            if not topic.locations:
                continue

            try:
                locs_data = json.loads(topic.locations)
                for loc in locs_data:
                    loc_name = loc.get("name", "").lower()
                    if loc_name in seen_names:
                        continue
                    seen_names.add(loc_name)

                    locations.append(
                        LocationContext(
                            name=loc.get("name", "Unknown"),
                            type=loc.get("type", "place"),
                            context=loc.get("context", "mentioned"),
                            topic_summary=topic.summary,
                        )
                    )
            except json.JSONDecodeError:
                continue

        logger.info(f"Found {len(locations)} relevant locations")
        return locations[:8]

    async def _get_group_context(self, message: Message) -> dict:
        """
        Get group context like destination and trip dates.

        Args:
            message: The incoming message

        Returns:
            Dict with group context info
        """
        context = {
            "destination": None,
            "trip_start": None,
            "trip_end": None,
        }

        if message.group:
            group = await self.session.get(Group, message.group.group_jid)
            if group:
                context["destination"] = group.destination_country
                context["trip_start"] = (
                    group.trip_start_date.strftime("%Y-%m-%d")
                    if group.trip_start_date
                    else None
                )
                context["trip_end"] = (
                    group.trip_end_date.strftime("%Y-%m-%d")
                    if group.trip_end_date
                    else None
                )

        return context

    async def _generate_recommendation(
        self,
        query: str,
        preferences: List[PreferenceInfo],
        locations: List[LocationContext],
        group_context: dict,
    ) -> str:
        """
        Generate a personalized recommendation using LLM.

        Args:
            query: The user's original query
            preferences: List of group preferences
            locations: List of relevant locations
            group_context: Group context info

        Returns:
            Generated recommendation string
        """
        # Format preferences
        pref_text = ""
        if preferences:
            pref_items = []
            for p in preferences[:10]:  # Limit
                pref_items.append(
                    f"- {p.mentioned_by} {'likes' if p.sentiment == 'positive' else 'dislikes' if p.sentiment == 'negative' else 'mentioned'}: {p.preference} ({p.category})"
                )
            pref_text = "\n".join(pref_items)

        # Format locations
        loc_text = ""
        if locations:
            loc_items = []
            for l in locations:
                status = "👍 recommended" if l.context == "recommended" else "⚠️ warned against" if l.context == "warned_against" else "mentioned"
                loc_items.append(f"- {l.name} ({l.type}) - {status}")
            loc_text = "\n".join(loc_items)

        # Format group context
        ctx_text = ""
        if group_context.get("destination"):
            ctx_text += f"Destination: {group_context['destination']}\n"
        if group_context.get("trip_start"):
            ctx_text += f"Trip dates: {group_context['trip_start']} to {group_context.get('trip_end', 'TBD')}\n"

        agent = Agent(
            model=self.settings.model_name,
            system_prompt=prompt_manager.render(
                "recommendation.j2",
                preferences=pref_text,
                locations=loc_text,
                group_context=ctx_text,
            ),
            output_type=str,
        )

        result = await agent.run(query)
        return result.output


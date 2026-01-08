"""Handler for location-aware queries in WhatsApp groups."""

import json
import logging
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


class LocationInfo(BaseModel):
    """Structured location data from KB topics."""

    name: str
    type: str
    context: str
    topic_summary: str
    speakers: str


class LocationQueryResult(BaseModel):
    """Result of a location search in the knowledge base."""

    location_name: str = Field(description="The name of the location found")
    found_in_kb: bool = Field(description="Whether the location was found in the knowledge base")
    group_context: str = Field(
        default="", description="Context from group discussions about this location"
    )
    location_type: Optional[str] = Field(
        default=None, description="Type of location (restaurant, hotel, etc.)"
    )


class LocationHandler(BaseHandler):
    """Handles location-related queries in WhatsApp groups."""

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
        Process a location-related query.

        Args:
            message: The incoming WhatsApp message
        """
        logger.info(
            f"LocationHandler called with message: {message.text[:50] if message.text else 'None'}..."
        )

        if not message.text:
            return

        # Search for locations in the knowledge base
        locations = await self._search_locations(message)

        if locations:
            # Generate enriched response using LLM
            response = await self._generate_location_response(message.text, locations)
        else:
            # No locations found - provide helpful response
            response = await self._generate_no_location_response(message.text)

        await self.send_message(message.chat_jid, response)

    async def _search_locations(self, message: Message) -> List[LocationInfo]:
        """
        Search the knowledge base for locations matching the user's query.

        Args:
            message: The incoming message

        Returns:
            List of LocationInfo objects found in KB
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

        # Search for topics with locations using vector similarity
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

        # Extract and deduplicate locations
        found_locations: List[LocationInfo] = []
        seen_names: set[str] = set()

        for topic in topics:
            if not topic.locations:
                continue

            try:
                locations_data = json.loads(topic.locations)
                for loc in locations_data:
                    loc_name = loc.get("name", "").lower()
                    # Skip duplicates
                    if loc_name in seen_names:
                        continue
                    seen_names.add(loc_name)

                    found_locations.append(
                        LocationInfo(
                            name=loc.get("name", "Unknown"),
                            type=loc.get("type", "place"),
                            context=loc.get("context", "mentioned"),
                            topic_summary=topic.summary,
                            speakers=topic.speakers,
                        )
                    )
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse locations JSON for topic {topic.id}")
                continue

        logger.info(f"Found {len(found_locations)} locations matching query")
        return found_locations[:5]  # Limit to top 5 most relevant

    async def _generate_location_response(
        self, query: str, locations: List[LocationInfo]
    ) -> str:
        """
        Generate an enriched response about locations using LLM.

        Args:
            query: The user's original query
            locations: List of locations found in KB

        Returns:
            Generated response string
        """
        # Format location context for the prompt
        location_context = "\n\n".join(
            [
                f"📍 **{loc.name}** ({loc.type})\n"
                f"- Context: {loc.context}\n"
                f"- Group discussion: {loc.topic_summary}\n"
                f"- Mentioned by: {loc.speakers}"
                for loc in locations
            ]
        )

        agent = Agent(
            model=self.settings.model_name,
            system_prompt=prompt_manager.render(
                "location_rag.j2", location_context=location_context
            ),
            output_type=str,
        )

        result = await agent.run(query)
        return result.output

    async def _generate_no_location_response(self, query: str) -> str:
        """
        Generate a helpful response when no locations are found.

        Args:
            query: The user's original query

        Returns:
            Friendly response indicating no locations found
        """
        agent = Agent(
            model=self.settings.model_name,
            system_prompt="""You are a helpful travel assistant. The user asked about a location, but you couldn't find it in the group's discussion history.

Respond in a friendly, helpful way:
1. Acknowledge you couldn't find info about this specific place in the group history
2. If you recognize the place from your knowledge, share a brief, helpful tidbit
3. Suggest they ask the group members who might have visited
4. Keep it short and conversational (2-3 sentences max)

Respond in the same language as the query (Hebrew or English).""",
            output_type=str,
        )

        result = await agent.run(query)
        return result.output


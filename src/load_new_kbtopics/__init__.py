import hashlib
import json
import logging
from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, PrivateAttr
from pydantic_ai import Agent, ModelSettings
from pydantic_ai.agent import AgentRunResult
from sqlmodel import desc, select
from sqlmodel.ext.asyncio.session import AsyncSession
from tenacity import (
    retry,
    wait_random_exponential,
    stop_after_attempt,
    before_sleep_log,
)
from voyageai.client_async import AsyncClient

from config import Settings, get_settings
from models import KBTopicCreate, Group, Message
from models.knowledge_base_topic import KBTopic
from models.upsert import bulk_upsert
from services.prompt_manager import prompt_manager
from utils.voyage_embed_text import voyage_embed_text
from whatsapp import WhatsAppClient

logger = logging.getLogger(__name__)


class Location(BaseModel):
    """A location mentioned in a conversation topic."""

    name: str = Field(description="The name of the place (e.g., 'Cafe Yafa', 'Central Park')")
    type: str = Field(
        description="Category of the location (restaurant, cafe, hotel, attraction, landmark, beach, neighborhood, city, etc.)"
    )
    context: Literal["recommended", "warned_against", "visited", "planned", "asked_about"] = Field(
        description="Why the location was mentioned in the conversation"
    )


class Event(BaseModel):
    """An event or plan mentioned in a conversation topic."""

    title: str = Field(description="Brief description of the event (e.g., 'Flight to Barcelona')")
    date: Optional[str] = Field(
        default=None,
        description="Date of the event in YYYY-MM-DD format, or null if unclear"
    )
    time: Optional[str] = Field(
        default=None,
        description="Time of the event in HH:MM format, or null if unclear"
    )
    type: Literal["flight", "hotel_checkin", "hotel_checkout", "activity", "tour", "reservation", "meeting", "deadline"] = Field(
        description="Category of the event"
    )
    context: Literal["confirmed", "tentative", "suggested", "cancelled"] = Field(
        description="Status of the event"
    )


class Preference(BaseModel):
    """A preference expressed by a group member."""

    category: Literal["food", "activity", "accommodation", "transport", "budget", "schedule"] = Field(
        description="What the preference relates to"
    )
    preference: str = Field(
        description="The specific preference (e.g., 'vegetarian', 'budget-friendly', 'adventure activities')"
    )
    sentiment: Literal["positive", "negative", "neutral"] = Field(
        description="How they feel about it"
    )
    mentioned_by: str = Field(
        description="The speaker tag who expressed this preference (e.g., '@user_1')"
    )


class TopicSentiment(BaseModel):
    """Sentiment analysis of a conversation topic."""

    overall: Literal["positive", "negative", "neutral", "mixed"] = Field(
        description="The dominant sentiment"
    )
    excitement: float = Field(
        ge=0.0, le=1.0,
        description="Level of excitement/enthusiasm (0.0 to 1.0)"
    )
    concern: float = Field(
        ge=0.0, le=1.0,
        description="Level of worry/concern (0.0 to 1.0)"
    )
    agreement: float = Field(
        ge=0.0, le=1.0,
        description="How much the group agrees on this topic (0.0 to 1.0)"
    )
    key_emotions: List[str] = Field(
        default_factory=list,
        description="List of notable emotions (excited, happy, worried, frustrated, etc.)"
    )


class Topic(BaseModel):
    subject: str = Field(description="The subject of the topic")
    summary: str = Field(
        description="A concise summary of the topic discussed. Credit notable insights to the speaker by tagging them (e.g, @user_1)"
    )
    locations: List[Location] = Field(
        default_factory=list,
        description="List of specific locations mentioned in this topic"
    )
    events: List[Event] = Field(
        default_factory=list,
        description="List of events or plans mentioned in this topic"
    )
    preferences: List[Preference] = Field(
        default_factory=list,
        description="List of preferences expressed in this topic"
    )
    sentiment: Optional[TopicSentiment] = Field(
        default=None,
        description="Sentiment analysis of this topic"
    )
    _speaker_map: Dict[str, str] = PrivateAttr()


def _deid_text(message: str, user_mapping: Dict[str, str]) -> str:
    for k, v in user_mapping.items():
        message = message.replace(f"@{k}", f"@{v}")
    return message


@retry(
    wait=wait_random_exponential(min=5, max=90, multiplier=1.5),
    stop=stop_after_attempt(6),
    before_sleep=before_sleep_log(logger, logging.DEBUG),
    reraise=True,
)
async def conversation_splitter_agent(
    settings: Settings, content: str
) -> AgentRunResult[List[Topic]]:
    agent = Agent(
        model=settings.model_name,
        # Set bigger then 1024 max token for this agent, because it's a long conversation
        model_settings=ModelSettings(max_tokens=10000),
        system_prompt=prompt_manager.render("conversation_splitter.j2"),
        output_type=List[Topic],
        retries=5,
    )

    return await agent.run(content)


def _get_speaker_mapping(messages: List[Message]) -> Dict[str, str]:
    i = 1
    sender_jids = {msg.sender_jid for msg in messages}
    speaker_mapping = {}
    for sender_jid in sender_jids:
        speaker_mapping[sender_jid] = f"user_{i}"
        i += 1

    for message in messages:
        # extract all regex @d+ from message.text and add them to speaker_mapping
        for speaker in (message.text or "").split():
            if speaker.startswith("@") and speaker[1:].isdigit():
                if speaker[1:] not in speaker_mapping:
                    speaker_mapping[speaker[1:]] = f"user_{i}"

    return speaker_mapping


def _topic_with_filtered_speakers(
    topic: Topic, speaker_mapping: Dict[str, str]
) -> Topic:
    # find all @user_d+ in topic.summary and topic.subject, then filter them from speaker_mapping
    speakers = set()
    for token in topic.summary.split():
        if token.startswith("@user_") and token[6:].isdigit():
            speakers.add(token[1:])
    for token in topic.subject.split():
        if token.startswith("@user_") and token[6:].isdigit():
            speakers.add(token[1:])

    topic._speaker_map = {v: k for k, v in speaker_mapping.items() if v in speakers}
    return topic


def split_messages(
    messages: List[Message],
    gap_hours: float = 2.0,
    min_size: int = 25,
    max_size: int = 200,
    overlap: int = 5,
) -> List[List[Message]]:
    """
    Split a list of messages into conversation chunks based on time gaps and size limits.
    Replicates the logic of split_chats but for Message objects without pandas.
    """
    if not messages:
        return []

    # Ensure sorted by timestamp
    messages.sort(key=lambda m: m.timestamp)

    # Step 1: Initial Splitting by time gap
    segments: List[List[Message]] = []
    current_segment: List[Message] = [messages[0]]

    for i in range(1, len(messages)):
        prev_msg = messages[i - 1]
        curr_msg = messages[i]
        time_diff = (curr_msg.timestamp - prev_msg.timestamp).total_seconds() / 3600

        if time_diff >= gap_hours:
            segments.append(current_segment)
            current_segment = []

        current_segment.append(curr_msg)

    if current_segment:
        segments.append(current_segment)

    # Step 2: Merge small segments
    merged_segments: List[List[Message]] = []
    buffer: List[Message] = []

    for segment in segments:
        if len(buffer) < min_size:
            buffer.extend(segment)
        else:
            merged_segments.append(buffer)
            buffer = list(segment)  # Start new buffer with current segment

    if buffer:
        merged_segments.append(buffer)

    # Step 3: Split large segments
    final_segments: List[List[Message]] = []
    for segment in merged_segments:
        while len(segment) > max_size:
            final_segments.append(segment[:max_size])
            segment = segment[max_size:]
        if segment:
            final_segments.append(segment)

    # Step 4: Add overlap
    overlapped_segments: List[List[Message]] = []
    for i, segment in enumerate(final_segments):
        if i > 0 and overlap > 0:
            # Get last 'overlap' messages from previous segment
            prev_overlap = final_segments[i - 1][-overlap:]
            # Combine with current segment
            segment = prev_overlap + segment

        overlapped_segments.append(segment)

    return overlapped_segments


async def get_conversation_topics(
    settings: Settings, messages: list[Message], my_number: str
) -> List[Topic]:
    if len(messages) == 0:
        return []

    speaker_mapping = _get_speaker_mapping(messages)
    speaker_mapping[my_number] = "bot"

    # Format conversation as "{timestamp}: {participant_enumeration}: {message}"
    # Swap tags in message to user tags E.G. "@972536150150 please comment" to "@user_1 please comment"
    conversation_content = "\n".join(
        [
            f"{message.timestamp}: @{speaker_mapping[message.sender_jid]}: {_deid_text(message.text, speaker_mapping)}"
            for message in messages
            if message.text is not None
        ]
    )

    result = await conversation_splitter_agent(settings, conversation_content)
    return [
        _topic_with_filtered_speakers(topic, speaker_mapping) for topic in result.output
    ]


async def load_topics(
    db_session: AsyncSession,
    group: Group,
    embedding_client: AsyncClient,
    topics: List[Topic],
    start_time: datetime,
    message_ids: List[str],
):
    if len(topics) == 0:
        return
    documents = [f"# {topic.subject}\n{topic.summary}" for topic in topics]
    topics_embeddings = await voyage_embed_text(embedding_client, documents)

    doc_models = [
        # TODO: Replace topic.subject with something else that is deterministic.
        # topic.subject is not deterministic because it's the result of the LLM.
        KBTopicCreate(
            id=str(
                hashlib.sha256(
                    f"{group.group_jid}_{start_time}_{topic.subject}".encode()
                ).hexdigest()
            ),
            embedding=emb,
            group_jid=group.group_jid,
            start_time=start_time,
            speakers=",".join(topic._speaker_map.values()),
            summary=_deid_text(topic.summary, topic._speaker_map),
            subject=_deid_text(topic.subject, topic._speaker_map),
            locations=json.dumps([loc.model_dump() for loc in topic.locations]) if topic.locations else None,
            events=json.dumps([evt.model_dump() for evt in topic.events]) if topic.events else None,
            preferences=json.dumps([pref.model_dump() for pref in topic.preferences]) if topic.preferences else None,
            sentiment=json.dumps(topic.sentiment.model_dump()) if topic.sentiment else None,
        )
        for topic, emb in zip(topics, topics_embeddings)
    ]
    # Once we give a meaningfull ID, we should migrate to upsert!
    await bulk_upsert(db_session, [KBTopic(**doc.model_dump()) for doc in doc_models])

    # Link topics to their source messages
    from models.kb_topic_message import KBTopicMessage

    for doc_model in doc_models:
        for message_id in message_ids:
            kb_topic_message = KBTopicMessage(
                kb_topic_id=doc_model.id,
                message_id=message_id,
            )
            db_session.add(kb_topic_message)

    # Update the group with the new last_ingest
    group.last_ingest = datetime.now()
    db_session.add(group)
    await db_session.commit()


class topicsLoader:
    async def load_topics(
        self,
        db_session: AsyncSession,
        group: Group,
        embedding_client: AsyncClient,
        whatsapp: WhatsAppClient,
    ):
        my_jid = await whatsapp.get_my_jid()
        try:
            # Since yesterday at 12:00 UTC. Between 24 hours to 48 hours ago
            stmt = (
                select(Message)
                .where(Message.timestamp >= group.last_ingest)
                .where(Message.group_jid == group.group_jid)
                .where(Message.sender_jid != my_jid.normalize_str())
                .order_by(desc(Message.timestamp))
            )
            res = await db_session.exec(stmt)
            # Convert Sequence to list explicitly
            messages = list(res.all())

            if len(messages) == 0:
                logger.info(f"No messages found for group {group.group_name}")
                return

            # The result from DB is ordered by timestamp descending (see stmt above).
            # We need them ascending for splitting.
            messages.sort(key=lambda m: m.timestamp)

            conversation_chunks = split_messages(messages)
            logger.info(
                f"Split {len(messages)} messages into {len(conversation_chunks)} conversation chunks for group {group.group_name}"
            )

            for i, chunk in enumerate(conversation_chunks):
                if not chunk:
                    continue
                start_time = chunk[0].timestamp
                logger.info(
                    f"Processing chunk {i + 1}/{len(conversation_chunks)} with {len(chunk)} messages for group {group.group_name}"
                )

                settings = get_settings()
                topics = await get_conversation_topics(settings, chunk, my_jid.user)
                logger.info(
                    f"Loading {len(topics)} topics from chunk {i + 1} for group {group.group_name}"
                )

                message_ids = [msg.message_id for msg in chunk]
                await load_topics(
                    db_session,
                    group,
                    embedding_client,
                    topics,
                    start_time,
                    message_ids,
                )

            logger.info(f"All topics loaded for group {group.group_name}")
        except Exception as e:
            logger.error(f"Error loading topics for group {group.group_name}: {str(e)}")
            raise

    async def load_topics_for_all_groups(
        self,
        session: AsyncSession,
        embedding_client: AsyncClient,
        whatsapp: WhatsAppClient,
    ):
        groups = await session.exec(select(Group).where(Group.managed == True))  # noqa: E712 https://stackoverflow.com/a/18998106
        for group in list(groups.all()):
            await self.load_topics(session, group, embedding_client, whatsapp)

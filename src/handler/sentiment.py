"""Handler for sentiment analysis and group mood queries in WhatsApp groups."""

import json
import logging
from typing import List, Optional

from pydantic import BaseModel
from pydantic_ai import Agent
from sqlmodel import select, col, desc
from sqlmodel.ext.asyncio.session import AsyncSession
from voyageai.client_async import AsyncClient

from config import Settings
from models import Message, KBTopic
from services.prompt_manager import prompt_manager
from whatsapp import WhatsAppClient
from .base_handler import BaseHandler

logger = logging.getLogger(__name__)


class SentimentInfo(BaseModel):
    """Sentiment data from a KB topic."""

    topic_subject: str
    overall: str
    excitement: float
    concern: float
    agreement: float
    key_emotions: List[str]


class SentimentHandler(BaseHandler):
    """Handles sentiment and group mood queries in WhatsApp groups."""

    def __init__(
        self,
        session: AsyncSession,
        whatsapp: WhatsAppClient,
        embedding_client: AsyncClient,
        settings: Settings,
    ):
        super().__init__(session, whatsapp, embedding_client)
        self.settings = settings

    async def analyze_group_sentiment(self, message: Message) -> Optional[str]:
        """
        Analyze recent group sentiment and return proactive message if needed.
        
        This can be called proactively to check if the group needs support.

        Args:
            message: The incoming message for context

        Returns:
            Proactive message if sentiment indicates need, None otherwise
        """
        sentiments = await self._get_recent_sentiments(message, limit=5)
        
        if not sentiments:
            return None

        # Check for concerning patterns
        avg_concern = sum(s.concern for s in sentiments) / len(sentiments)
        avg_agreement = sum(s.agreement for s in sentiments) / len(sentiments)
        
        # High concern detected
        if avg_concern > 0.7:
            concerned_topics = [s.topic_subject for s in sentiments if s.concern > 0.6]
            if concerned_topics:
                return (
                    f"נראה שיש קצת חששות בקבוצה לגבי {concerned_topics[0]}. "
                    "אפשר לעזור עם משהו? 🤔"
                )

        # Low agreement - group can't decide
        if avg_agreement < 0.3:
            disagreed_topics = [s.topic_subject for s in sentiments if s.agreement < 0.4]
            if disagreed_topics:
                return (
                    f"שמתי לב שיש חילוקי דעות לגבי {disagreed_topics[0]}. "
                    "אולי כדאי להצביע? 🗳️"
                )

        return None

    async def __call__(self, message: Message) -> None:
        """
        Process a sentiment/mood query.

        Args:
            message: The incoming WhatsApp message
        """
        logger.info(
            f"SentimentHandler called with message: {message.text[:50] if message.text else 'None'}..."
        )

        if not message.text:
            return

        # Get sentiment data from recent topics
        sentiments = await self._get_recent_sentiments(message)

        if sentiments:
            response = await self._generate_sentiment_response(message.text, sentiments)
        else:
            response = await self._generate_no_sentiment_response(message.text)

        await self.send_message(message.chat_jid, response)

    async def _get_recent_sentiments(
        self, message: Message, limit: int = 10
    ) -> List[SentimentInfo]:
        """
        Get sentiment data from recent KB topics.

        Args:
            message: The incoming message
            limit: Maximum number of topics to analyze

        Returns:
            List of SentimentInfo objects
        """
        group_jids = None
        if message.group:
            group_jids = [message.group.group_jid]

        # Get recent topics with sentiment data
        q = (
            select(KBTopic)
            .where(col(KBTopic.sentiment).isnot(None))
            .order_by(desc(KBTopic.start_time))
            .limit(limit)
        )

        if group_jids:
            q = q.where(col(KBTopic.group_jid).in_(group_jids))

        result = await self.session.exec(q)
        topics = result.all()

        sentiments: List[SentimentInfo] = []
        for topic in topics:
            if not topic.sentiment:
                continue

            try:
                sent_data = json.loads(topic.sentiment)
                sentiments.append(
                    SentimentInfo(
                        topic_subject=topic.subject,
                        overall=sent_data.get("overall", "neutral"),
                        excitement=sent_data.get("excitement", 0.5),
                        concern=sent_data.get("concern", 0.0),
                        agreement=sent_data.get("agreement", 0.5),
                        key_emotions=sent_data.get("key_emotions", []),
                    )
                )
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse sentiment JSON for topic {topic.id}")
                continue

        logger.info(f"Found {len(sentiments)} topics with sentiment data")
        return sentiments

    async def _generate_sentiment_response(
        self, query: str, sentiments: List[SentimentInfo]
    ) -> str:
        """
        Generate a response about group sentiment using LLM.

        Args:
            query: The user's original query
            sentiments: List of sentiment data

        Returns:
            Generated response string
        """
        # Calculate averages
        avg_excitement = sum(s.excitement for s in sentiments) / len(sentiments)
        avg_concern = sum(s.concern for s in sentiments) / len(sentiments)
        avg_agreement = sum(s.agreement for s in sentiments) / len(sentiments)

        # Collect emotions
        all_emotions = []
        for s in sentiments:
            all_emotions.extend(s.key_emotions)
        emotion_counts = {}
        for e in all_emotions:
            emotion_counts[e] = emotion_counts.get(e, 0) + 1
        top_emotions = sorted(emotion_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        # Format sentiment context
        sentiment_context = f"""
## Overall Group Mood Analysis:
- Excitement level: {avg_excitement:.0%}
- Concern level: {avg_concern:.0%}
- Agreement level: {avg_agreement:.0%}
- Top emotions: {', '.join(e[0] for e in top_emotions) if top_emotions else 'Not detected'}

## Recent Topic Sentiments:
"""
        for s in sentiments[:5]:
            sentiment_context += f"- {s.topic_subject}: {s.overall} (excitement: {s.excitement:.0%}, concern: {s.concern:.0%})\n"

        agent = Agent(
            model=self.settings.model_name,
            system_prompt=f"""You are בוטיול, a helpful travel group assistant. The user is asking about the group's mood or sentiment.

{sentiment_context}

Your task:
1. Summarize the group's overall mood based on the data
2. Highlight any topics with strong positive or negative sentiment
3. If there are concerns, acknowledge them empathetically
4. If excitement is high, match that energy!
5. If agreement is low on some topics, suggest resolving it

Guidelines:
- Be empathetic and supportive
- Don't just recite numbers - interpret them naturally
- Respond in the same language as the query (Hebrew or English)
- Keep it conversational and friendly
- Use appropriate emojis to match the mood""",
            output_type=str,
        )

        result = await agent.run(query)
        return result.output

    async def _generate_no_sentiment_response(self, query: str) -> str:
        """
        Generate a response when no sentiment data is available.

        Args:
            query: The user's original query

        Returns:
            Friendly response
        """
        agent = Agent(
            model=self.settings.model_name,
            system_prompt="""You are a helpful travel assistant. The user asked about group mood/sentiment, but you don't have enough conversation history to analyze yet.

Respond in a friendly way:
1. Acknowledge you don't have enough data yet
2. Mention you're learning from the group's conversations
3. Suggest they keep chatting and you'll pick up on the vibes
4. Keep it short and light-hearted

Respond in the same language as the query (Hebrew or English).""",
            output_type=str,
        )

        result = await agent.run(query)
        return result.output


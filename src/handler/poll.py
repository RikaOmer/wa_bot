"""Handler for group polls and voting in WhatsApp groups."""

import json
import logging
import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession
from voyageai.client_async import AsyncClient

from config import Settings
from models import Message, Sender
from models.poll import Poll
from models.upsert import upsert
from whatsapp import WhatsAppClient
from whatsapp.jid import normalize_jid, parse_jid
from .base_handler import BaseHandler

logger = logging.getLogger(__name__)


class ParsedPollRequest(BaseModel):
    """Parsed poll creation request."""

    action: str = Field(description="Action: create, vote, results, close")
    question: Optional[str] = Field(default=None, description="Poll question")
    options: List[str] = Field(default_factory=list, description="Poll options")
    vote_option: Optional[int] = Field(default=None, description="Option index to vote for (1-based)")


class PollHandler(BaseHandler):
    """Handles poll creation and voting in WhatsApp groups."""

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
        Process a poll-related request.

        Args:
            message: The incoming WhatsApp message
        """
        logger.info(
            f"PollHandler called with message: {message.text[:50] if message.text else 'None'}..."
        )

        if not message.text:
            return

        if not message.group_jid:
            await self.send_message(
                message.chat_jid,
                "❌ הצבעות עובדות רק בקבוצות.",
            )
            return

        # Parse the poll request
        parsed = await self._parse_poll_request(message.text)

        match parsed.action:
            case "create":
                await self._handle_create_poll(message, parsed)
            case "vote":
                await self._handle_vote(message, parsed)
            case "results":
                await self._handle_results(message)
            case "close":
                await self._handle_close_poll(message)
            case _:
                await self._handle_help(message)

    async def _parse_poll_request(self, text: str) -> ParsedPollRequest:
        """
        Parse the poll request using LLM.

        Args:
            text: The message text

        Returns:
            ParsedPollRequest with parsed data
        """
        agent = Agent(
            model=self.settings.model_name,
            system_prompt="""Parse the user's poll request.

Actions:
- "create": User wants to create a new poll (look for "הצבעה", "poll", "vote on", questions with options)
- "vote": User wants to vote (look for numbers like "1", "2", "אופציה 1", "option 2")
- "results": User wants to see results (look for "תוצאות", "results", "מי הצביע")
- "close": User wants to close a poll (look for "סגור", "close", "סיים")
- "help": Anything else

For create:
- Extract the question
- Extract options (separated by "או", "or", commas, or line breaks)

For vote:
- Extract the option number (1-based)

Examples:
- "הצבעה: פיצה או סושי?" → create, question="פיצה או סושי?", options=["פיצה", "סושי"]
- "1" or "אופציה 1" → vote, vote_option=1
- "תוצאות ההצבעה" → results
- "סגור הצבעה" → close""",
            output_type=ParsedPollRequest,
        )

        result = await agent.run(text)
        return result.output

    async def _handle_create_poll(
        self, message: Message, parsed: ParsedPollRequest
    ) -> None:
        """Create a new poll."""
        if not parsed.question or len(parsed.options) < 2:
            await self.send_message(
                message.chat_jid,
                "❌ צריך שאלה עם לפחות 2 אופציות.\n"
                "דוגמה: \"הצבעה: פיצה או סושי או המבורגר\"",
            )
            return

        # Check for existing open poll
        existing = await self._get_active_poll(message.group_jid)
        if existing:
            await self.send_message(
                message.chat_jid,
                "❌ כבר יש הצבעה פתוחה בקבוצה.\n"
                "תגידו \"תוצאות\" לראות אותה או \"סגור הצבעה\" לסגור.",
            )
            return

        # Ensure sender exists
        await self._ensure_sender_exists(message.sender_jid, message.sender.push_name if message.sender else None)

        # Create poll
        poll = Poll(
            group_jid=message.group_jid,
            question=parsed.question,
            options=json.dumps(parsed.options),
            votes="{}",
            created_by_jid=normalize_jid(message.sender_jid),
        )
        self.session.add(poll)
        await self.session.commit()

        # Format response
        options_text = "\n".join(
            f"{i+1}. {opt}" for i, opt in enumerate(parsed.options)
        )

        await self.send_message(
            message.chat_jid,
            f"🗳️ **הצבעה חדשה!**\n\n"
            f"❓ {parsed.question}\n\n"
            f"{options_text}\n\n"
            f"להצביע - תגידו את מספר האופציה (1, 2, וכו')\n"
            f"ההצבעה תיסגר אוטומטית אחרי 24 שעות.",
        )

    async def _handle_vote(
        self, message: Message, parsed: ParsedPollRequest
    ) -> None:
        """Handle a vote on the active poll."""
        poll = await self._get_active_poll(message.group_jid)
        if not poll:
            await self.send_message(
                message.chat_jid,
                "❌ אין הצבעה פתוחה כרגע.\n"
                "תייגו אותי עם \"הצבעה: שאלה או אופציה1 או אופציה2\" ליצירת הצבעה.",
            )
            return

        if not parsed.vote_option:
            await self.send_message(
                message.chat_jid,
                "❌ לא הבנתי על מה להצביע. תגידו מספר (1, 2, וכו')",
            )
            return

        options = json.loads(poll.options)
        if parsed.vote_option < 1 or parsed.vote_option > len(options):
            await self.send_message(
                message.chat_jid,
                f"❌ אין אופציה {parsed.vote_option}. יש רק {len(options)} אופציות.",
            )
            return

        # Record vote
        votes = json.loads(poll.votes)
        voter_jid = normalize_jid(message.sender_jid)
        option_key = str(parsed.vote_option - 1)  # 0-indexed in storage

        # Remove previous vote if exists
        for opt_key in votes:
            if voter_jid in votes[opt_key]:
                votes[opt_key].remove(voter_jid)

        # Add new vote
        if option_key not in votes:
            votes[option_key] = []
        votes[option_key].append(voter_jid)

        poll.votes = json.dumps(votes)
        self.session.add(poll)
        await self.session.commit()

        # Get voter display name
        voter_name = await self._get_display_name(voter_jid)
        chosen_option = options[parsed.vote_option - 1]

        await self.send_message(
            message.chat_jid,
            f"✅ {voter_name} הצביע/ה: **{chosen_option}**",
        )

    async def _handle_results(self, message: Message) -> None:
        """Show poll results."""
        poll = await self._get_active_poll(message.group_jid)
        if not poll:
            # Check for closed polls
            poll = await self._get_latest_poll(message.group_jid)
            if not poll:
                await self.send_message(
                    message.chat_jid,
                    "❌ אין הצבעות בקבוצה.",
                )
                return

        options = json.loads(poll.options)
        votes = json.loads(poll.votes)

        # Count votes
        results = []
        total_votes = 0
        for i, opt in enumerate(options):
            opt_votes = len(votes.get(str(i), []))
            total_votes += opt_votes
            results.append((opt, opt_votes))

        # Sort by votes
        results.sort(key=lambda x: x[1], reverse=True)

        # Format results
        status = "🔴 סגורה" if poll.is_closed else "🟢 פתוחה"
        results_text = "\n".join(
            f"{'🥇' if i == 0 and r[1] > 0 else '  '} {r[0]}: {r[1]} הצבעות"
            for i, r in enumerate(results)
        )

        await self.send_message(
            message.chat_jid,
            f"🗳️ **תוצאות הצבעה** ({status})\n\n"
            f"❓ {poll.question}\n\n"
            f"{results_text}\n\n"
            f"סה\"כ: {total_votes} הצבעות",
        )

    async def _handle_close_poll(self, message: Message) -> None:
        """Close the active poll."""
        poll = await self._get_active_poll(message.group_jid)
        if not poll:
            await self.send_message(
                message.chat_jid,
                "❌ אין הצבעה פתוחה לסגירה.",
            )
            return

        poll.closed_at = datetime.now(timezone.utc)
        self.session.add(poll)
        await self.session.commit()

        # Show final results
        await self._handle_results(message)

    async def _handle_help(self, message: Message) -> None:
        """Show poll help."""
        await self.send_message(
            message.chat_jid,
            "🗳️ **איך להצביע:**\n\n"
            "📝 **ליצור הצבעה:**\n"
            "\"הצבעה: פיצה או סושי או המבורגר\"\n\n"
            "✅ **להצביע:**\n"
            "פשוט תגידו את מספר האופציה (1, 2, וכו')\n\n"
            "📊 **לראות תוצאות:**\n"
            "\"תוצאות הצבעה\"\n\n"
            "🔒 **לסגור הצבעה:**\n"
            "\"סגור הצבעה\"",
        )

    async def _get_active_poll(self, group_jid: str) -> Optional[Poll]:
        """Get the active (open) poll for a group."""
        q = (
            select(Poll)
            .where(Poll.group_jid == group_jid)
            .where(Poll.closed_at.is_(None))
            .order_by(Poll.created_at.desc())
        )
        result = await self.session.exec(q)
        poll = result.first()

        # Check if auto-closed
        if poll and poll.is_closed:
            poll.closed_at = datetime.now(timezone.utc)
            self.session.add(poll)
            await self.session.commit()
            return None

        return poll

    async def _get_latest_poll(self, group_jid: str) -> Optional[Poll]:
        """Get the most recent poll for a group."""
        q = (
            select(Poll)
            .where(Poll.group_jid == group_jid)
            .order_by(Poll.created_at.desc())
            .limit(1)
        )
        result = await self.session.exec(q)
        return result.first()

    async def _ensure_sender_exists(
        self, jid: str, push_name: Optional[str]
    ) -> None:
        """Ensure a sender record exists in the database."""
        sender = await self.session.get(Sender, jid)
        if sender is None:
            sender = Sender(jid=jid, push_name=push_name)
            await upsert(self.session, sender)
            await self.session.flush()

    async def _get_display_name(self, jid: str) -> str:
        """Get display name for a JID."""
        sender = await self.session.get(Sender, jid)
        if sender and sender.push_name:
            return sender.push_name

        parsed = parse_jid(jid)
        return f"@{parsed.user}"


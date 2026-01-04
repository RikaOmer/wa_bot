"""Handler for Splitwise-like expense tracking in WhatsApp groups."""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from voyageai.client_async import AsyncClient

from config import Settings
from models import Message, Sender, Expense, ExpenseParticipant
from models.upsert import upsert
from services.prompt_manager import prompt_manager
from whatsapp import WhatsAppClient
from whatsapp.jid import normalize_jid, parse_jid
from .base_handler import BaseHandler

logger = logging.getLogger(__name__)

# Maximum expense amount in agorot (100,000 ILS = 10,000,000 agorot)
MAX_EXPENSE_AGOROT = 10_000_000


class ExpenseIntentEnum(str, Enum):
    add_expense = "add_expense"
    query_balance = "query_balance"
    unknown = "unknown"


class ParticipantType(str, Enum):
    everyone = "everyone"
    mentioned = "mentioned"


class ParsedExpense(BaseModel):
    """Structured expense data extracted by LLM."""

    intent: ExpenseIntentEnum = Field(
        description="The intent of the message: add_expense, query_balance, or unknown"
    )
    is_valid_currency: bool = Field(
        default=True,
        description="False if non-shekel currency was detected (dollars, euros, etc.)",
    )
    amount_agorot: Optional[int] = Field(
        default=None,
        description="Amount in agorot (1/100 shekel). E.g., 50 shekels = 5000 agorot",
    )
    description: Optional[str] = Field(
        default=None,
        description="What the expense was for",
    )
    participant_type: ParticipantType = Field(
        default=ParticipantType.everyone,
        description="Whether expense is for everyone or only mentioned users",
    )
    mentioned_users: list[str] = Field(
        default_factory=list,
        description="List of @mentioned phone numbers (if participant_type is 'mentioned')",
    )


@dataclass
class Settlement:
    """Represents a debt settlement between two people."""

    from_jid: str
    to_jid: str
    amount_agorot: int


class ExpenseHandler(BaseHandler):
    """Handles expense tracking commands in WhatsApp groups."""

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
        Process an expense-related message.

        Args:
            message: The incoming WhatsApp message
        """
        logger.info(f"ExpenseHandler called with message: {message.text[:50] if message.text else 'None'}...")

        if not message.text:
            return

        if not message.group_jid:
            await self.send_message(
                message.chat_jid,
                "❌ פיצ'ר ההוצאות עובד רק בקבוצות.",
            )
            return

        logger.info(f"Processing expense for group: {message.group_jid}")

        # Parse the message using LLM
        parsed = await self._parse_expense(message.text)
        logger.info(f"Parsed expense: intent={parsed.intent}, amount={parsed.amount_agorot}, valid_currency={parsed.is_valid_currency}")

        if not parsed.is_valid_currency:
            await self.send_message(
                message.chat_jid,
                "❌ אני תומך רק בשקלים. אנא כתוב את הסכום בשקלים.",
            )
            return

        match parsed.intent:
            case ExpenseIntentEnum.add_expense:
                await self._handle_add_expense(message, parsed)
            case ExpenseIntentEnum.query_balance:
                await self._handle_query_balance(message)
            case ExpenseIntentEnum.unknown:
                await self.send_message(
                    message.chat_jid,
                    "לא הבנתי. אפשר להוסיף הוצאה (למשל: 'שילמתי 50 שקל על פיצה לכולם') "
                    "או לשאול על המאזן ('כמה כל אחד חייב?').",
                )

    async def _parse_expense(self, text: str) -> ParsedExpense:
        """
        Use LLM to extract structured expense data from message text.

        Args:
            text: The message text to parse

        Returns:
            ParsedExpense with extracted data
        """
        agent = Agent(
            model=self.settings.model_name,
            system_prompt=prompt_manager.render("expense_parser.j2"),
            output_type=ParsedExpense,
        )

        result = await agent.run(text)
        parsed = result.output

        # Extract mentioned users from text (format: @972501234567)
        if parsed.participant_type == ParticipantType.mentioned:
            mentioned = re.findall(r"@(\d+)", text)
            parsed.mentioned_users = mentioned

        return parsed

    async def _handle_add_expense(
        self, message: Message, parsed: ParsedExpense
    ) -> None:
        """
        Add a new expense to the database.

        Args:
            message: The original message
            parsed: Parsed expense data from LLM
        """
        logger.info(f"Adding expense: amount={parsed.amount_agorot}, desc={parsed.description}")

        if not parsed.amount_agorot or parsed.amount_agorot <= 0:
            await self.send_message(
                message.chat_jid,
                "❌ לא הצלחתי לזהות סכום תקין. נסה שוב עם סכום בשקלים.",
            )
            return

        if parsed.amount_agorot > MAX_EXPENSE_AGOROT:
            await self.send_message(
                message.chat_jid,
                f"❌ הסכום גבוה מדי (מקסימום {MAX_EXPENSE_AGOROT // 100:,}₪). נא לבדוק את הסכום.",
            )
            return

        # Get bot's JID to exclude from participants
        my_jid = await self.whatsapp.get_my_jid()
        my_jid_normalized = normalize_jid(str(my_jid))

        # Get participants from message history (these are phone number JIDs)
        # This is more reliable than the WhatsApp API which returns LID JIDs
        logger.info(f"Fetching participants from message history for: {message.group_jid}")
        participant_jids = await self._get_group_participants_from_history(
            message.group_jid, my_jid_normalized
        )
        logger.info(f"Found {len(participant_jids)} participants from message history")

        # Get payer's JID (will be added to participants if tagging specific people)
        payer_jid = normalize_jid(message.sender_jid)

        # Determine participants based on type
        if parsed.participant_type == ParticipantType.mentioned:
            # Use mentioned users + the payer (payer is always a participant)
            mentioned_jids = [
                normalize_jid(f"{user}@s.whatsapp.net")
                for user in parsed.mentioned_users
            ]
            # Validate mentioned users are known (have sent messages)
            known_jids = set(participant_jids)
            valid_mentioned = [j for j in mentioned_jids if j in known_jids]

            if not valid_mentioned:
                await self.send_message(
                    message.chat_jid,
                    "❌ לא מצאתי את האנשים שתייגת. האם הם שלחו הודעה בקבוצה?",
                )
                return

            # Add the payer to the participants (they're also part of the expense)
            participant_jids = list(set(valid_mentioned + [payer_jid]))
            logger.info(f"Mentioned expense: {len(valid_mentioned)} tagged + payer = {len(participant_jids)} total participants")

        if len(participant_jids) < 2:
            await self.send_message(
                message.chat_jid,
                "❌ צריך לפחות 2 אנשים כדי לחלק הוצאה.\n"
                "💡 כדי להירשם, כל חבר קבוצה צריך לשלוח הודעה כלשהי (למשל 'היי').",
            )
            return

        # Calculate shares
        num_participants = len(participant_jids)
        base_share = parsed.amount_agorot // num_participants
        remainder = parsed.amount_agorot % num_participants

        # Ensure senders exist in database
        await self._ensure_sender_exists(payer_jid, message.sender.push_name if message.sender else None)

        for jid in participant_jids:
            await self._ensure_sender_exists(jid, None)

        # Create the expense
        expense = Expense(
            group_jid=message.group_jid,
            payer_jid=payer_jid,
            amount_agorot=parsed.amount_agorot,
            description=parsed.description,
        )
        self.session.add(expense)
        await self.session.flush()  # Get the expense ID
        logger.info(f"Created expense with ID: {expense.id}")

        # Create participant shares
        for i, jid in enumerate(participant_jids):
            # Assign remainder to first participant (or could be payer)
            share = base_share + (1 if i < remainder else 0)
            participant = ExpenseParticipant(
                expense_id=expense.id,
                participant_jid=jid,
                share_agorot=share,
            )
            self.session.add(participant)

        await self.session.commit()

        # Send confirmation
        amount_display = expense.format_amount()
        per_person = base_share / 100
        per_person_display = f"{per_person:.2f}₪" if per_person != int(per_person) else f"{int(per_person)}₪"

        description_text = f" על {parsed.description}" if parsed.description else ""

        await self.send_message(
            message.chat_jid,
            f"✅ נרשם! שילמת {amount_display}{description_text}.\n"
            f"חולק בין {num_participants} אנשים ({per_person_display} לכל אחד)",
        )

    async def _handle_query_balance(self, message: Message) -> None:
        """
        Calculate and display current balances for the group.

        Args:
            message: The original message
        """
        logger.info(f"Querying balances for group: {message.group_jid}")
        balances = await self._get_balances(message.group_jid)
        logger.info(f"Got balances: {balances}")

        if not balances:
            await self.send_message(
                message.chat_jid,
                "📊 אין הוצאות רשומות עדיין בקבוצה הזו.",
            )
            return

        # Calculate settlements
        settlements = self._calculate_settlements(balances)

        if not settlements:
            await self.send_message(
                message.chat_jid,
                "📊 הכל מסודר! אין חובות פתוחים.",
            )
            return

        # Get total expenses for info
        total_stmt = (
            select(Expense)
            .where(Expense.group_jid == message.group_jid)
        )
        result = await self.session.exec(total_stmt)
        all_expenses = result.all()
        total_amount = sum(e.amount_agorot for e in all_expenses)

        # Build response message
        lines = ["📊 מאזן הוצאות:", ""]

        for settlement in settlements:
            from_name = await self._get_display_name(settlement.from_jid)
            to_name = await self._get_display_name(settlement.to_jid)
            amount = settlement.amount_agorot / 100
            amount_str = f"{amount:.2f}₪" if amount != int(amount) else f"{int(amount)}₪"
            lines.append(f"{from_name} חייב/ת ל{to_name}: {amount_str}")

        lines.append("")
        total_display = total_amount / 100
        total_str = f"{total_display:.2f}₪" if total_display != int(total_display) else f"{int(total_display)}₪"
        lines.append(f"סה\"כ הוצאות בקבוצה: {total_str}")

        await self.send_message(
            message.chat_jid,
            "\n".join(lines),
        )

    async def _get_balances(self, group_jid: str) -> dict[str, int]:
        """
        Calculate net balance for each person in the group.

        Positive balance = owed money (paid more than fair share)
        Negative balance = owes money (paid less than fair share)

        Args:
            group_jid: The group JID

        Returns:
            Dict mapping JID to balance in agorot
        """
        # Get all expenses for this group
        stmt = select(Expense).where(Expense.group_jid == group_jid)
        result = await self.session.exec(stmt)
        expenses = result.all()

        logger.info(f"Found {len(expenses)} expenses for group {group_jid}")

        if not expenses:
            return {}

        balances: dict[str, int] = {}

        for expense in expenses:
            logger.info(f"Processing expense {expense.id}: amount={expense.amount_agorot}, participants={len(expense.participants)}")
            # Payer gets credited the full amount
            payer_jid = expense.payer_jid
            balances[payer_jid] = balances.get(payer_jid, 0) + expense.amount_agorot

            # Each participant gets debited their share
            for participant in expense.participants:
                jid = participant.participant_jid
                balances[jid] = balances.get(jid, 0) - participant.share_agorot

        # Filter out zero balances
        return {jid: bal for jid, bal in balances.items() if bal != 0}

    def _calculate_settlements(
        self, balances: dict[str, int]
    ) -> list[Settlement]:
        """
        Calculate optimal settlements to resolve all debts.

        Uses greedy algorithm: match largest creditor with largest debtor.

        Args:
            balances: Dict mapping JID to balance (positive = owed, negative = owes)

        Returns:
            List of Settlement objects describing who pays whom
        """
        if not balances:
            return []

        # Separate into creditors (positive) and debtors (negative)
        creditors = [(jid, bal) for jid, bal in balances.items() if bal > 0]
        debtors = [(jid, -bal) for jid, bal in balances.items() if bal < 0]

        # Sort by amount (descending)
        creditors.sort(key=lambda x: x[1], reverse=True)
        debtors.sort(key=lambda x: x[1], reverse=True)

        settlements: list[Settlement] = []

        # Make mutable copies
        cred_list = list(creditors)
        debt_list = list(debtors)

        while cred_list and debt_list:
            creditor_jid, credit_amount = cred_list[0]
            debtor_jid, debt_amount = debt_list[0]

            # Settle the minimum of the two amounts
            settle_amount = min(credit_amount, debt_amount)

            if settle_amount > 0:
                settlements.append(
                    Settlement(
                        from_jid=debtor_jid,
                        to_jid=creditor_jid,
                        amount_agorot=settle_amount,
                    )
                )

            # Update amounts
            new_credit = credit_amount - settle_amount
            new_debt = debt_amount - settle_amount

            # Remove or update creditor
            cred_list.pop(0)
            if new_credit > 0:
                cred_list.insert(0, (creditor_jid, new_credit))
                cred_list.sort(key=lambda x: x[1], reverse=True)

            # Remove or update debtor
            debt_list.pop(0)
            if new_debt > 0:
                debt_list.insert(0, (debtor_jid, new_debt))
                debt_list.sort(key=lambda x: x[1], reverse=True)

        return settlements

    async def _get_group_participants_from_history(
        self, group_jid: str, exclude_jid: str
    ) -> list[str]:
        """
        Get list of participants from message history in this group.
        
        This is more reliable than the WhatsApp API which may return LID JIDs.
        Only returns phone number JIDs (@s.whatsapp.net).
        
        Args:
            group_jid: The group JID
            exclude_jid: JID to exclude (typically the bot)
            
        Returns:
            List of unique participant JIDs who have sent messages
        """
        # Get distinct senders from message history for this group
        stmt = (
            select(Message.sender_jid)
            .where(Message.group_jid == group_jid)
            .distinct()
        )
        result = await self.session.exec(stmt)
        all_senders = result.all()
        
        # Filter to only phone number JIDs, exclude bot
        participant_jids = []
        for sender_jid in all_senders:
            if not sender_jid:
                continue
            normalized = normalize_jid(sender_jid)
            # Skip bot
            if normalized == exclude_jid:
                continue
            # Skip LID JIDs (only use phone number JIDs)
            if "@lid" in sender_jid:
                continue
            # Only include @s.whatsapp.net JIDs
            if "@s.whatsapp.net" in sender_jid:
                participant_jids.append(normalized)
        
        return participant_jids

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
        """
        Get display name for a JID.
        Returns push_name if available, otherwise phone number with @.
        """
        sender = await self.session.get(Sender, jid)
        if sender and sender.push_name:
            return sender.push_name

        # Extract phone number from JID
        parsed = parse_jid(jid)
        return f"@{parsed.user}"


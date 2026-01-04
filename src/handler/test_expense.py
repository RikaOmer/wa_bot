"""Unit tests for the ExpenseHandler."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pydantic_ai import Agent
from pydantic_ai.agent import AgentRunResult

from handler.expense import (
    ExpenseHandler,
    ParsedExpense,
    ExpenseIntentEnum,
    ParticipantType,
    Settlement,
)
from models import Message, Group, Sender, Expense, ExpenseParticipant
from test_utils.mock_session import AsyncSessionMock
from whatsapp import SendMessageRequest
from whatsapp.jid import JID
from whatsapp.models import Participant
from config import Settings


@pytest.fixture
def mock_whatsapp():
    client = AsyncMock()
    client.send_message = AsyncMock()
    client.get_my_jid = AsyncMock(
        return_value=JID(user="bot", server="s.whatsapp.net")
    )
    # Mock group members
    client.get_group_members = AsyncMock(
        return_value=[
            Participant(
                JID="972501111111@s.whatsapp.net",
                IsAdmin=False,
                IsSuperAdmin=False,
            ),
            Participant(
                JID="972502222222@s.whatsapp.net",
                IsAdmin=False,
                IsSuperAdmin=False,
            ),
            Participant(
                JID="972503333333@s.whatsapp.net",
                IsAdmin=False,
                IsSuperAdmin=False,
            ),
            Participant(
                JID="bot@s.whatsapp.net",
                IsAdmin=False,
                IsSuperAdmin=False,
            ),
        ]
    )
    return client


@pytest.fixture
def mock_embedding_client():
    return AsyncMock()


@pytest.fixture
def mock_settings():
    return Mock(spec=Settings, model_name="test-model")


@pytest.fixture
def group_message():
    """A message from a group context."""
    msg = Message(
        message_id="test_msg_1",
        text="שילמתי 100 שקל על פיצה לכולם",
        chat_jid="120363123456789012@g.us",
        sender_jid="972501111111@s.whatsapp.net",
        group_jid="120363123456789012@g.us",
        timestamp=datetime.now(timezone.utc),
    )
    msg.sender = Sender(jid="972501111111@s.whatsapp.net", push_name="דני")
    msg.group = Group(group_jid="120363123456789012@g.us", group_name="Test Group")
    return msg


@pytest.fixture
def private_message():
    """A private (non-group) message."""
    return Message(
        message_id="test_msg_2",
        text="שילמתי 50 שקל",
        chat_jid="972501111111@s.whatsapp.net",
        sender_jid="972501111111@s.whatsapp.net",
        timestamp=datetime.now(timezone.utc),
    )


def create_mock_agent(return_value):
    """Helper to create a mocked Agent.run result."""
    mock = Mock()
    mock.run = AsyncMock(return_value=AgentRunResult(output=return_value))
    return mock


class TestExpenseHandlerRouting:
    """Test the main routing logic of ExpenseHandler."""

    @pytest.mark.asyncio
    async def test_rejects_non_group_messages(
        self,
        mock_session: AsyncSessionMock,
        mock_whatsapp: AsyncMock,
        mock_embedding_client: AsyncMock,
        mock_settings: Mock,
        private_message: Message,
    ):
        """Expense tracking should only work in groups."""
        # Mock send_message response
        mock_response = AsyncMock()
        mock_response.results.message_id = "response_id"
        mock_whatsapp.send_message.return_value = mock_response

        handler = ExpenseHandler(
            mock_session, mock_whatsapp, mock_embedding_client, mock_settings
        )
        await handler(private_message)

        # Should send an error message about groups only
        mock_whatsapp.send_message.assert_called_once()
        call_args = mock_whatsapp.send_message.call_args[0][0]
        assert "קבוצות" in call_args.message

    @pytest.mark.asyncio
    async def test_rejects_non_shekel_currency(
        self,
        mock_session: AsyncSessionMock,
        mock_whatsapp: AsyncMock,
        mock_embedding_client: AsyncMock,
        mock_settings: Mock,
        group_message: Message,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Should reject expenses in non-shekel currencies."""
        # Mock LLM to return invalid currency
        parsed = ParsedExpense(
            intent=ExpenseIntentEnum.add_expense,
            is_valid_currency=False,
            amount_agorot=5000,
            description="אוכל",
        )
        mock_agent = create_mock_agent(parsed)
        monkeypatch.setattr(Agent, "__init__", lambda *args, **kwargs: None)
        monkeypatch.setattr(Agent, "run", mock_agent.run)

        mock_response = AsyncMock()
        mock_response.results.message_id = "response_id"
        mock_whatsapp.send_message.return_value = mock_response

        handler = ExpenseHandler(
            mock_session, mock_whatsapp, mock_embedding_client, mock_settings
        )
        await handler(group_message)

        # Should send currency error message
        call_args = mock_whatsapp.send_message.call_args[0][0]
        assert "שקלים" in call_args.message

    @pytest.mark.asyncio
    async def test_handles_unknown_intent(
        self,
        mock_session: AsyncSessionMock,
        mock_whatsapp: AsyncMock,
        mock_embedding_client: AsyncMock,
        mock_settings: Mock,
        group_message: Message,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Should provide help message for unknown intents."""
        parsed = ParsedExpense(
            intent=ExpenseIntentEnum.unknown,
        )
        mock_agent = create_mock_agent(parsed)
        monkeypatch.setattr(Agent, "__init__", lambda *args, **kwargs: None)
        monkeypatch.setattr(Agent, "run", mock_agent.run)

        mock_response = AsyncMock()
        mock_response.results.message_id = "response_id"
        mock_whatsapp.send_message.return_value = mock_response

        handler = ExpenseHandler(
            mock_session, mock_whatsapp, mock_embedding_client, mock_settings
        )
        await handler(group_message)

        call_args = mock_whatsapp.send_message.call_args[0][0]
        assert "לא הבנתי" in call_args.message


class TestAddExpense:
    """Test adding expenses."""

    @pytest.mark.asyncio
    async def test_add_expense_for_everyone(
        self,
        mock_session: AsyncSessionMock,
        mock_whatsapp: AsyncMock,
        mock_embedding_client: AsyncMock,
        mock_settings: Mock,
        group_message: Message,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Should add an expense split among all group members."""
        parsed = ParsedExpense(
            intent=ExpenseIntentEnum.add_expense,
            is_valid_currency=True,
            amount_agorot=10000,  # 100 shekels
            description="פיצה",
            participant_type=ParticipantType.everyone,
        )
        mock_agent = create_mock_agent(parsed)
        monkeypatch.setattr(Agent, "__init__", lambda *args, **kwargs: None)
        monkeypatch.setattr(Agent, "run", mock_agent.run)

        mock_response = AsyncMock()
        mock_response.results.message_id = "response_id"
        mock_whatsapp.send_message.return_value = mock_response

        handler = ExpenseHandler(
            mock_session, mock_whatsapp, mock_embedding_client, mock_settings
        )
        await handler(group_message)

        # Verify success message
        call_args = mock_whatsapp.send_message.call_args[0][0]
        assert "נרשם" in call_args.message
        assert "100₪" in call_args.message
        assert "פיצה" in call_args.message

    @pytest.mark.asyncio
    async def test_rejects_zero_amount(
        self,
        mock_session: AsyncSessionMock,
        mock_whatsapp: AsyncMock,
        mock_embedding_client: AsyncMock,
        mock_settings: Mock,
        group_message: Message,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Should reject expenses with zero or negative amounts."""
        parsed = ParsedExpense(
            intent=ExpenseIntentEnum.add_expense,
            is_valid_currency=True,
            amount_agorot=0,
            description="משהו",
        )
        mock_agent = create_mock_agent(parsed)
        monkeypatch.setattr(Agent, "__init__", lambda *args, **kwargs: None)
        monkeypatch.setattr(Agent, "run", mock_agent.run)

        mock_response = AsyncMock()
        mock_response.results.message_id = "response_id"
        mock_whatsapp.send_message.return_value = mock_response

        handler = ExpenseHandler(
            mock_session, mock_whatsapp, mock_embedding_client, mock_settings
        )
        await handler(group_message)

        call_args = mock_whatsapp.send_message.call_args[0][0]
        assert "סכום תקין" in call_args.message

    @pytest.mark.asyncio
    async def test_rejects_excessive_amount(
        self,
        mock_session: AsyncSessionMock,
        mock_whatsapp: AsyncMock,
        mock_embedding_client: AsyncMock,
        mock_settings: Mock,
        group_message: Message,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Should reject amounts over the maximum limit."""
        parsed = ParsedExpense(
            intent=ExpenseIntentEnum.add_expense,
            is_valid_currency=True,
            amount_agorot=20_000_000,  # 200,000 shekels (over limit)
            description="יאכטה",
        )
        mock_agent = create_mock_agent(parsed)
        monkeypatch.setattr(Agent, "__init__", lambda *args, **kwargs: None)
        monkeypatch.setattr(Agent, "run", mock_agent.run)

        mock_response = AsyncMock()
        mock_response.results.message_id = "response_id"
        mock_whatsapp.send_message.return_value = mock_response

        handler = ExpenseHandler(
            mock_session, mock_whatsapp, mock_embedding_client, mock_settings
        )
        await handler(group_message)

        call_args = mock_whatsapp.send_message.call_args[0][0]
        assert "גבוה מדי" in call_args.message


class TestQueryBalance:
    """Test balance queries."""

    @pytest.mark.asyncio
    async def test_no_expenses_message(
        self,
        mock_session: AsyncSessionMock,
        mock_whatsapp: AsyncMock,
        mock_embedding_client: AsyncMock,
        mock_settings: Mock,
        group_message: Message,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Should show message when no expenses exist."""
        group_message.text = "כמה כל אחד חייב?"

        parsed = ParsedExpense(intent=ExpenseIntentEnum.query_balance)
        mock_agent = create_mock_agent(parsed)
        monkeypatch.setattr(Agent, "__init__", lambda *args, **kwargs: None)
        monkeypatch.setattr(Agent, "run", mock_agent.run)

        mock_response = AsyncMock()
        mock_response.results.message_id = "response_id"
        mock_whatsapp.send_message.return_value = mock_response

        handler = ExpenseHandler(
            mock_session, mock_whatsapp, mock_embedding_client, mock_settings
        )
        await handler(group_message)

        call_args = mock_whatsapp.send_message.call_args[0][0]
        assert "אין הוצאות" in call_args.message


class TestSettlementAlgorithm:
    """Test the debt settlement calculation algorithm."""

    def test_simple_two_person_settlement(self):
        """A owes B 50."""
        handler = ExpenseHandler.__new__(ExpenseHandler)

        balances = {
            "A@s.whatsapp.net": 5000,   # A is owed 50 shekels
            "B@s.whatsapp.net": -5000,  # B owes 50 shekels
        }

        settlements = handler._calculate_settlements(balances)

        assert len(settlements) == 1
        assert settlements[0].from_jid == "B@s.whatsapp.net"
        assert settlements[0].to_jid == "A@s.whatsapp.net"
        assert settlements[0].amount_agorot == 5000

    def test_three_person_settlement(self):
        """A paid 150 for 3 people, so B and C each owe A 50."""
        handler = ExpenseHandler.__new__(ExpenseHandler)

        # A paid 150, owes 50 (their share) = +100 net
        # B owes 50
        # C owes 50
        balances = {
            "A@s.whatsapp.net": 10000,   # A is owed 100 shekels
            "B@s.whatsapp.net": -5000,   # B owes 50 shekels
            "C@s.whatsapp.net": -5000,   # C owes 50 shekels
        }

        settlements = handler._calculate_settlements(balances)

        assert len(settlements) == 2
        total_settled = sum(s.amount_agorot for s in settlements)
        assert total_settled == 10000

        # All payments should go to A
        for s in settlements:
            assert s.to_jid == "A@s.whatsapp.net"

    def test_complex_multi_person_settlement(self):
        """Multiple creditors and debtors."""
        handler = ExpenseHandler.__new__(ExpenseHandler)

        balances = {
            "A@s.whatsapp.net": 10000,   # A is owed 100
            "B@s.whatsapp.net": 5000,    # B is owed 50
            "C@s.whatsapp.net": -8000,   # C owes 80
            "D@s.whatsapp.net": -7000,   # D owes 70
        }

        settlements = handler._calculate_settlements(balances)

        # Verify total debits equal total credits
        total_to_creditors = sum(
            s.amount_agorot for s in settlements
            if s.to_jid in ["A@s.whatsapp.net", "B@s.whatsapp.net"]
        )
        assert total_to_creditors == 15000  # 100 + 50

    def test_empty_balances(self):
        """No balances should result in no settlements."""
        handler = ExpenseHandler.__new__(ExpenseHandler)

        settlements = handler._calculate_settlements({})
        assert len(settlements) == 0

    def test_all_balanced(self):
        """When everyone has zero balance, no settlements needed."""
        handler = ExpenseHandler.__new__(ExpenseHandler)

        balances = {
            "A@s.whatsapp.net": 0,
            "B@s.whatsapp.net": 0,
        }

        # Filter out zeros first (as the real code does)
        filtered = {k: v for k, v in balances.items() if v != 0}
        settlements = handler._calculate_settlements(filtered)

        assert len(settlements) == 0

    def test_remainder_distribution(self):
        """Test that remainders are handled correctly when splitting."""
        # 100 agorot split among 3 people = 33 + 33 + 34
        handler = ExpenseHandler.__new__(ExpenseHandler)

        # Simulate: A paid 100 for 3 people
        # Each owes 33.33... but we use integers
        # A paid 100, share is 33 = +67
        # B share is 33 = -33
        # C share is 34 (gets remainder) = -34

        balances = {
            "A@s.whatsapp.net": 67,
            "B@s.whatsapp.net": -33,
            "C@s.whatsapp.net": -34,
        }

        settlements = handler._calculate_settlements(balances)

        # Total should balance out
        total_to_a = sum(s.amount_agorot for s in settlements if s.to_jid == "A@s.whatsapp.net")
        assert total_to_a == 67


class TestAmountFormatting:
    """Test amount formatting helpers."""

    def test_format_whole_number(self):
        """Whole shekel amounts should not show decimals."""
        expense = Expense(
            id=1,
            group_jid="test@g.us",
            payer_jid="test@s.whatsapp.net",
            amount_agorot=10000,
            description="test",
        )
        assert expense.format_amount() == "100₪"

    def test_format_decimal_amount(self):
        """Fractional amounts should show two decimals."""
        expense = Expense(
            id=1,
            group_jid="test@g.us",
            payer_jid="test@s.whatsapp.net",
            amount_agorot=15050,
            description="test",
        )
        assert expense.format_amount() == "150.50₪"

    def test_format_participant_share(self):
        """Test participant share formatting."""
        participant = ExpenseParticipant(
            expense_id=1,
            participant_jid="test@s.whatsapp.net",
            share_agorot=3333,
        )
        assert participant.format_share() == "33.33₪"


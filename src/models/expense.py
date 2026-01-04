"""Expense tracking models for Splitwise-like functionality."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from pydantic import field_validator
from sqlmodel import Field, Relationship, SQLModel, Column, DateTime, Index

from whatsapp.jid import normalize_jid

if TYPE_CHECKING:
    from .group import Group
    from .sender import Sender


class Expense(SQLModel, table=True):
    """
    Represents a shared expense in a WhatsApp group.
    Amounts are stored in agorot (1/100 shekel) to avoid floating-point issues.
    """

    __tablename__: str = "expense"

    id: Optional[int] = Field(default=None, primary_key=True)
    group_jid: str = Field(
        max_length=255,
        foreign_key="group.group_jid",
        index=True,
    )
    payer_jid: str = Field(
        max_length=255,
        foreign_key="sender.jid",
    )
    amount_agorot: int = Field(
        description="Total amount in agorot (1/100 shekel)",
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Description of the expense",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    # Relationships
    group: Optional["Group"] = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"}
    )
    payer: Optional["Sender"] = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"}
    )
    participants: List["ExpenseParticipant"] = Relationship(
        back_populates="expense",
        sa_relationship_kwargs={"lazy": "selectin", "cascade": "all, delete-orphan"},
    )

    __table_args__ = (
        Index("idx_expense_group_created", "group_jid", "created_at"),
    )

    @field_validator("group_jid", "payer_jid", mode="before")
    @classmethod
    def normalize(cls, value: Optional[str]) -> Optional[str]:
        return normalize_jid(value) if value else None

    @property
    def amount_shekels(self) -> float:
        """Return amount in shekels (for display purposes)."""
        return self.amount_agorot / 100

    def format_amount(self) -> str:
        """Format amount as a string with shekel symbol."""
        amount = self.amount_shekels
        if amount == int(amount):
            return f"{int(amount)}₪"
        return f"{amount:.2f}₪"


class ExpenseParticipant(SQLModel, table=True):
    """
    Links an expense to its participants and their share amounts.
    """

    __tablename__: str = "expense_participant"

    expense_id: int = Field(
        foreign_key="expense.id",
        primary_key=True,
    )
    participant_jid: str = Field(
        max_length=255,
        foreign_key="sender.jid",
        primary_key=True,
    )
    share_agorot: int = Field(
        description="This participant's share in agorot",
    )

    # Relationships
    expense: Optional["Expense"] = Relationship(
        back_populates="participants",
    )
    participant: Optional["Sender"] = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"}
    )

    @field_validator("participant_jid", mode="before")
    @classmethod
    def normalize(cls, value: Optional[str]) -> Optional[str]:
        return normalize_jid(value) if value else None

    @property
    def share_shekels(self) -> float:
        """Return share in shekels (for display purposes)."""
        return self.share_agorot / 100

    def format_share(self) -> str:
        """Format share as a string with shekel symbol."""
        amount = self.share_shekels
        if amount == int(amount):
            return f"{int(amount)}₪"
        return f"{amount:.2f}₪"


Expense.model_rebuild()
ExpenseParticipant.model_rebuild()


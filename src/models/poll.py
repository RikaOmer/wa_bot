"""Poll model for group voting functionality."""

from datetime import datetime, timezone
from typing import Optional, List

from sqlmodel import Field, SQLModel, Column, DateTime, Text


class Poll(SQLModel, table=True):
    """Poll model for group voting."""

    id: Optional[int] = Field(default=None, primary_key=True)
    group_jid: str = Field(max_length=255, foreign_key="group.group_jid")
    question: str = Field(max_length=500)
    # JSON array of option strings
    options: str = Field(sa_column=Column(Text))
    # JSON object: {option_index: [voter_jids]}
    votes: str = Field(default="{}", sa_column=Column(Text))
    created_by_jid: str = Field(max_length=255, foreign_key="sender.jid")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    closed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    # Auto-close after this many hours (None = manual close only)
    auto_close_hours: Optional[int] = Field(default=24)

    @property
    def is_closed(self) -> bool:
        """Check if the poll is closed."""
        if self.closed_at:
            return True
        if self.auto_close_hours:
            elapsed = (datetime.now(timezone.utc) - self.created_at).total_seconds() / 3600
            return elapsed >= self.auto_close_hours
        return False


"""Itinerary model for trip planning."""

from datetime import date, datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel, Column, DateTime, Text


class ItineraryItem(SQLModel, table=True):
    """Itinerary item model for trip planning."""

    __tablename__ = "itinerary_item"

    id: Optional[int] = Field(default=None, primary_key=True)
    group_jid: str = Field(max_length=255, foreign_key="group.group_jid", index=True)
    item_date: date = Field(index=True)
    time_slot: str = Field(max_length=50)  # morning, afternoon, evening, or HH:MM
    title: str = Field(max_length=255)
    location: Optional[str] = Field(default=None, max_length=255)
    notes: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_by_jid: str = Field(max_length=255, foreign_key="sender.jid")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from pydantic import field_validator
from sqlmodel import Field, Relationship, SQLModel, Column, DateTime, Text

from whatsapp.jid import normalize_jid

if TYPE_CHECKING:
    from .group import Group
    from .sender import Sender


class TripAlbum(SQLModel, table=True):
    """
    Links a WhatsApp group to a Google Photos album.
    Stores OAuth tokens for uploading photos on behalf of the group admin.
    """

    __tablename__: str = "trip_album"

    group_jid: str = Field(
        primary_key=True,
        max_length=255,
        foreign_key="group.group_jid",
    )
    album_id: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Google Photos album ID",
    )
    album_title: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Album title in Google Photos",
    )
    google_refresh_token: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="Encrypted OAuth refresh token",
    )
    google_access_token: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="Current OAuth access token",
    )
    token_expiry: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
        description="Access token expiration time",
    )
    created_by_jid: Optional[str] = Field(
        default=None,
        max_length=255,
        foreign_key="sender.jid",
        description="JID of the user who set up the album",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    # Relationships
    group: Optional["Group"] = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"}
    )
    created_by: Optional["Sender"] = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"}
    )

    @field_validator("group_jid", "created_by_jid", mode="before")
    @classmethod
    def normalize(cls, value: Optional[str]) -> Optional[str]:
        return normalize_jid(value) if value else None

    def is_token_expired(self) -> bool:
        """Check if the access token is expired or about to expire (5 min buffer)."""
        if not self.token_expiry:
            return True
        buffer = 300  # 5 minutes
        return datetime.now(timezone.utc).timestamp() >= (
            self.token_expiry.timestamp() - buffer
        )


TripAlbum.model_rebuild()


"""add trip_album table

Revision ID: c7d8e9f0a1b2
Revises: b2c3d4e5f6g7
Create Date: 2026-01-04

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, None] = "b2c3d4e5f6g7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trip_album",
        sa.Column("group_jid", sa.String(length=255), primary_key=True),
        sa.Column("album_id", sa.String(length=255), nullable=True),
        sa.Column("album_title", sa.String(length=255), nullable=True),
        sa.Column("google_refresh_token", sa.Text(), nullable=True),
        sa.Column("google_access_token", sa.Text(), nullable=True),
        sa.Column("token_expiry", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_jid", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_jid"], ["group.group_jid"]),
        sa.ForeignKeyConstraint(["created_by_jid"], ["sender.jid"]),
    )


def downgrade() -> None:
    op.drop_table("trip_album")





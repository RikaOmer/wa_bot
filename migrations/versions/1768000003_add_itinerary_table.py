"""add itinerary_item table for trip planning

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-01-08

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "itinerary_item",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("group_jid", sa.String(length=255), nullable=False),
        sa.Column("item_date", sa.Date(), nullable=False),
        sa.Column("time_slot", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_jid", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_jid"], ["group.group_jid"]),
        sa.ForeignKeyConstraint(["created_by_jid"], ["sender.jid"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_itinerary_group_jid", "itinerary_item", ["group_jid"])
    op.create_index("idx_itinerary_date", "itinerary_item", ["item_date"])


def downgrade() -> None:
    op.drop_index("idx_itinerary_date")
    op.drop_index("idx_itinerary_group_jid")
    op.drop_table("itinerary_item")


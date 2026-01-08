"""add poll table for group voting

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-01-08

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "poll",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("group_jid", sa.String(length=255), nullable=False),
        sa.Column("question", sa.String(length=500), nullable=False),
        sa.Column("options", sa.Text(), nullable=False),
        sa.Column("votes", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_by_jid", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_close_hours", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["group_jid"], ["group.group_jid"]),
        sa.ForeignKeyConstraint(["created_by_jid"], ["sender.jid"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_poll_group_jid", "poll", ["group_jid"])


def downgrade() -> None:
    op.drop_index("idx_poll_group_jid")
    op.drop_table("poll")


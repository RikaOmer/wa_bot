"""add pending_approval and added_by_jid to group

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-01-08

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add pending_approval field - tracks if the group is waiting for admin approval
    op.add_column(
        "group",
        sa.Column(
            "pending_approval", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    # Add added_by_jid field - stores who added the bot to the group
    op.add_column(
        "group",
        sa.Column("added_by_jid", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("group", "added_by_jid")
    op.drop_column("group", "pending_approval")


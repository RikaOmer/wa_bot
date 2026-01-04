"""add expense tables

Revision ID: d1e2f3a4b5c6
Revises: c7d8e9f0a1b2
Create Date: 2026-01-04

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create expense table
    op.create_table(
        "expense",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("group_jid", sa.String(length=255), nullable=False),
        sa.Column("payer_jid", sa.String(length=255), nullable=False),
        sa.Column("amount_agorot", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_jid"], ["group.group_jid"]),
        sa.ForeignKeyConstraint(["payer_jid"], ["sender.jid"]),
    )
    op.create_index("idx_expense_group_created", "expense", ["group_jid", "created_at"])
    op.create_index("ix_expense_group_jid", "expense", ["group_jid"])

    # Create expense_participant table
    op.create_table(
        "expense_participant",
        sa.Column("expense_id", sa.Integer(), nullable=False),
        sa.Column("participant_jid", sa.String(length=255), nullable=False),
        sa.Column("share_agorot", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["expense_id"], ["expense.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["participant_jid"], ["sender.jid"]),
        sa.PrimaryKeyConstraint("expense_id", "participant_jid"),
    )


def downgrade() -> None:
    op.drop_table("expense_participant")
    op.drop_index("idx_expense_group_created", table_name="expense")
    op.drop_index("ix_expense_group_jid", table_name="expense")
    op.drop_table("expense")


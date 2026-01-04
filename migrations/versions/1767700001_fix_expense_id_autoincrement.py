"""fix expense id autoincrement

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-01-04

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the existing tables and recreate with proper auto-increment
    op.drop_table("expense_participant")
    op.drop_index("idx_expense_group_created", table_name="expense")
    op.drop_index("ix_expense_group_jid", table_name="expense")
    op.drop_table("expense")

    # Recreate expense table with SERIAL for auto-increment
    op.execute("""
        CREATE TABLE expense (
            id SERIAL PRIMARY KEY,
            group_jid VARCHAR(255) NOT NULL REFERENCES "group"(group_jid),
            payer_jid VARCHAR(255) NOT NULL REFERENCES sender(jid),
            amount_agorot INTEGER NOT NULL,
            description VARCHAR(500),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
    """)
    op.create_index("idx_expense_group_created", "expense", ["group_jid", "created_at"])
    op.create_index("ix_expense_group_jid", "expense", ["group_jid"])

    # Recreate expense_participant table
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
    # Drop and recreate without SERIAL (back to original broken state)
    op.drop_table("expense_participant")
    op.drop_index("idx_expense_group_created", table_name="expense")
    op.drop_index("ix_expense_group_jid", table_name="expense")
    op.drop_table("expense")

    # Recreate original tables
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

    op.create_table(
        "expense_participant",
        sa.Column("expense_id", sa.Integer(), nullable=False),
        sa.Column("participant_jid", sa.String(length=255), nullable=False),
        sa.Column("share_agorot", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["expense_id"], ["expense.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["participant_jid"], ["sender.jid"]),
        sa.PrimaryKeyConstraint("expense_id", "participant_jid"),
    )


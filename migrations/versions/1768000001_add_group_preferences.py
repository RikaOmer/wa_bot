"""add group_preferences field to group table

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-01-08

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add group_preferences field - JSON object with aggregated preferences
    op.add_column(
        "group",
        sa.Column("group_preferences", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("group", "group_preferences")


"""add events, preferences, and sentiment fields to kbtopic

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-01-08

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add events field - JSON array of event objects
    op.add_column(
        "kbtopic",
        sa.Column("events", sa.Text(), nullable=True),
    )
    # Add preferences field - JSON array of preference objects
    op.add_column(
        "kbtopic",
        sa.Column("preferences", sa.Text(), nullable=True),
    )
    # Add sentiment field - JSON sentiment analysis object
    op.add_column(
        "kbtopic",
        sa.Column("sentiment", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("kbtopic", "sentiment")
    op.drop_column("kbtopic", "preferences")
    op.drop_column("kbtopic", "events")


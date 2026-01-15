"""add trip_context field to group table

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-01-08

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add trip_context field - stores trip context/purpose (e.g., "מסיבת רווקים", "טיול משפחתי")
    op.add_column(
        "group",
        sa.Column("trip_context", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("group", "trip_context")





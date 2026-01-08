"""add locations field to kbtopic

Revision ID: e5f6a7b8c9d0
Revises: a1b2c3d4e5f9
Create Date: 2026-01-08

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "a1b2c3d4e5f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add locations field - JSON array of location objects [{name, type, context}, ...]
    op.add_column(
        "kbtopic",
        sa.Column("locations", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("kbtopic", "locations")


"""add welcome and trip tracking fields to group

Revision ID: a1b2c3d4e5f9
Revises: f3a4b5c6d7e8
Create Date: 2026-01-07

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f9"
down_revision: Union[str, None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add welcomed field - tracks if the bot has sent a welcome message
    op.add_column(
        "group",
        sa.Column("welcomed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    # Add destination_country field - stores the trip destination
    op.add_column(
        "group",
        sa.Column("destination_country", sa.String(length=100), nullable=True),
    )
    # Add trip_start_date field - optional trip start date
    op.add_column(
        "group",
        sa.Column("trip_start_date", sa.DateTime(timezone=True), nullable=True),
    )
    # Add trip_end_date field - optional trip end date
    op.add_column(
        "group",
        sa.Column("trip_end_date", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("group", "trip_end_date")
    op.drop_column("group", "trip_start_date")
    op.drop_column("group", "destination_country")
    op.drop_column("group", "welcomed")





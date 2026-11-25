"""Link bookings cleanly to slot_holds via nullable slot_hold_id foreign key.

Revision ID: 20261125_0002
Revises: 20261125_0001
Create Date: 2026-11-25 14:15:00+00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261125_0002"
down_revision: str | Sequence[str] | None = "20261125_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "bookings",
        sa.Column("slot_hold_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_bookings_slot_hold_id",
        "bookings",
        "slot_holds",
        ["slot_hold_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_bookings_slot_hold_id", "bookings", ["slot_hold_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_bookings_slot_hold_id", table_name="bookings")
    op.drop_constraint("fk_bookings_slot_hold_id", "bookings", type_="foreignkey")
    op.drop_column("bookings", "slot_hold_id")

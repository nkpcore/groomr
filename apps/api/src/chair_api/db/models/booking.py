"""Authoritative booking, snapshot items, concurrency allocations, holds, and walk-ins."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from chair_api.db.base import Base, UUIDTimestampMixin


class Booking(UUIDTimestampMixin, Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("source IN ('PLATFORM', 'WALK_IN')", name="valid_booking_source"),
        CheckConstraint("booking_mode IN ('INSTANT', 'REQUEST')", name="valid_booking_mode"),
        CheckConstraint(
            "status IN ('HELD', 'REQUESTED', 'CONFIRMED', 'CHECKED_IN', "
            "'IN_SERVICE', 'COMPLETED', 'CANCELLED', 'EXPIRED', 'NO_SHOW')",
            name="valid_booking_status",
        ),
        CheckConstraint("total_price_paise >= 0", name="non_negative_total_price"),
        CheckConstraint("discount_paise >= 0", name="non_negative_discount"),
        CheckConstraint("net_payable_paise >= 0", name="non_negative_net_payable"),
        CheckConstraint("scheduled_end_at > scheduled_start_at", name="valid_booking_window"),
        Index("ix_bookings_branch_start", "branch_id", "scheduled_start_at"),
        Index("ix_bookings_customer_created", "customer_user_id", "created_at"),
    )

    booking_code: Mapped[str] = mapped_column(String(24), nullable=False, unique=True)
    customer_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    slot_hold_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("slot_holds.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="PLATFORM")
    booking_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="INSTANT")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="HELD")
    scheduled_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_price_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    discount_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    net_payable_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    is_featured_attribution: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    check_in_otp_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    completion_otp_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_by_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class BookingItem(UUIDTimestampMixin, Base):
    __tablename__ = "booking_items"
    __table_args__ = (
        CheckConstraint("unit_price_paise_snapshot >= 0", name="non_negative_snapshot_price"),
        CheckConstraint("duration_minutes_snapshot > 0", name="positive_snapshot_duration"),
        Index("ix_booking_items_booking_id", "booking_id"),
    )

    booking_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False
    )
    branch_service_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branch_services.id", ondelete="SET NULL"), nullable=True
    )
    service_name_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    category_snapshot: Mapped[str] = mapped_column(String(32), nullable=False)
    unit_price_paise_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_minutes_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    buffer_before_minutes_snapshot: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    buffer_after_minutes_snapshot: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class WalkIn(UUIDTimestampMixin, Base):
    __tablename__ = "walk_ins"
    __table_args__ = (
        CheckConstraint(
            "status IN ('WAITING', 'SEATED', 'IN_SERVICE', 'COMPLETED', 'CANCELLED', 'NO_SHOW')",
            name="valid_walk_in_status",
        ),
        CheckConstraint("quoted_price_paise >= 0", name="non_negative_walk_in_price"),
        CheckConstraint("estimated_duration_minutes > 0", name="positive_walk_in_duration"),
        Index("ix_walk_ins_branch_status", "branch_id", "status"),
    )

    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False
    )
    staff_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff.id", ondelete="SET NULL"), nullable=True
    )
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resources.id", ondelete="SET NULL"), nullable=True
    )
    customer_name: Mapped[str] = mapped_column(String(120), nullable=False)
    customer_phone_e164: Mapped[str | None] = mapped_column(String(20), nullable=True)
    customer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    service_summary: Mapped[str] = mapped_column(String(255), nullable=False)
    quoted_price_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    queue_position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="WAITING")
    checked_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BookingAllocation(UUIDTimestampMixin, Base):
    __tablename__ = "booking_allocations"
    __table_args__ = (
        CheckConstraint(
            "booking_id IS NOT NULL OR walk_in_id IS NOT NULL",
            name="allocation_has_owner",
        ),
        ExcludeConstraint(
            ("staff_id", "="),
            ("allocated_range", "&&"),
            name="uq_active_staff_allocation",
            using="gist",
            where=text("is_active = true"),
        ),
        ExcludeConstraint(
            ("resource_id", "="),
            ("allocated_range", "&&"),
            name="uq_active_resource_allocation",
            using="gist",
            where=text("is_active = true AND resource_id IS NOT NULL"),
        ),
        Index("ix_booking_allocations_branch", "branch_id"),
    )

    booking_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bookings.id", ondelete="CASCADE"), nullable=True
    )
    walk_in_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("walk_ins.id", ondelete="CASCADE"), nullable=True
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False
    )
    staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff.id", ondelete="RESTRICT"), nullable=False
    )
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resources.id", ondelete="RESTRICT"), nullable=True
    )
    allocated_range: Mapped[Any] = mapped_column(TSTZRANGE, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SlotHold(UUIDTimestampMixin, Base):
    __tablename__ = "slot_holds"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'CONVERTED', 'RELEASED', 'EXPIRED')",
            name="valid_slot_hold_status",
        ),
        ExcludeConstraint(
            ("staff_id", "="),
            ("hold_range", "&&"),
            name="uq_active_staff_hold",
            using="gist",
            where=text("status = 'ACTIVE'"),
        ),
        ExcludeConstraint(
            ("resource_id", "="),
            ("hold_range", "&&"),
            name="uq_active_resource_hold",
            using="gist",
            where=text("status = 'ACTIVE' AND resource_id IS NOT NULL"),
        ),
        Index("ix_slot_holds_expires_status", "expires_at", "status"),
    )

    customer_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False
    )
    staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff.id", ondelete="CASCADE"), nullable=False
    )
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resources.id", ondelete="CASCADE"), nullable=True
    )
    hold_range: Mapped[Any] = mapped_column(TSTZRANGE, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)


class IdempotencyKey(UUIDTimestampMixin, Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("actor_key", "endpoint", "idempotency_key", name="uq_actor_endpoint_key"),
    )

    actor_key: Mapped[str] = mapped_column(String(128), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(160), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

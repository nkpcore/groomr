"""Service catalog, branch pricing, staff, shifts, schedule blocks, and chairs."""

import uuid
from datetime import time
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, UUID
from sqlalchemy.orm import Mapped, mapped_column

from chair_api.db.base import Base, UUIDTimestampMixin


class Service(UUIDTimestampMixin, Base):
    __tablename__ = "services"
    __table_args__ = (
        CheckConstraint(
            "category IN ('HAIRCUT', 'BEARD', 'SHAVE', 'FACIAL', 'PACKAGE', 'COLOR')",
            name="valid_service_category",
        ),
        CheckConstraint("default_duration_minutes > 0", name="positive_default_duration"),
    )

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name_en: Mapped[str] = mapped_column(String(120), nullable=False)
    name_hi: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    default_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class BranchService(UUIDTimestampMixin, Base):
    __tablename__ = "branch_services"
    __table_args__ = (
        UniqueConstraint("branch_id", "service_id", name="uq_branch_service"),
        CheckConstraint("price_paise >= 0", name="non_negative_price_paise"),
        CheckConstraint("duration_minutes > 0", name="positive_duration_minutes"),
        CheckConstraint("buffer_before_minutes >= 0", name="non_negative_buffer_before"),
        CheckConstraint("buffer_after_minutes >= 0", name="non_negative_buffer_after"),
        Index("ix_branch_services_branch_active", "branch_id", "is_active"),
    )

    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("services.id", ondelete="RESTRICT"), nullable=False
    )
    display_name_en: Mapped[str] = mapped_column(String(140), nullable=False)
    display_name_hi: Mapped[str] = mapped_column(String(140), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    buffer_before_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    buffer_after_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Staff(UUIDTimestampMixin, Base):
    __tablename__ = "staff"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'ON_LEAVE', 'INACTIVE')", name="valid_staff_status"),
        Index("ix_staff_branch_status", "branch_id", "status"),
    )

    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    specializations_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    portfolio_keys_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    is_verified_staff: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_accepting_bookings: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")


class StaffService(UUIDTimestampMixin, Base):
    __tablename__ = "staff_services"
    __table_args__ = (
        UniqueConstraint("staff_id", "branch_service_id", name="uq_staff_branch_service"),
        CheckConstraint(
            "custom_duration_minutes IS NULL OR custom_duration_minutes > 0",
            name="positive_custom_duration",
        ),
    )

    staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff.id", ondelete="CASCADE"), nullable=False
    )
    branch_service_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branch_services.id", ondelete="CASCADE"), nullable=False
    )
    custom_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class StaffShift(UUIDTimestampMixin, Base):
    __tablename__ = "staff_shifts"
    __table_args__ = (
        CheckConstraint("weekday >= 0 AND weekday <= 6", name="valid_weekday"),
        CheckConstraint("end_time_local > start_time_local", name="valid_shift_window"),
        Index("ix_staff_shifts_staff_weekday", "staff_id", "weekday"),
    )

    staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff.id", ondelete="CASCADE"), nullable=False
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False
    )
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time_local: Mapped[time] = mapped_column(Time, nullable=False)
    end_time_local: Mapped[time] = mapped_column(Time, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ScheduleBlock(UUIDTimestampMixin, Base):
    __tablename__ = "schedule_blocks"
    __table_args__ = (
        CheckConstraint(
            "block_type IN ('BREAK', 'LEAVE', 'HOLIDAY', 'MAINTENANCE')",
            name="valid_block_type",
        ),
        Index("ix_schedule_blocks_branch_staff", "branch_id", "staff_id"),
    )

    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False
    )
    staff_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff.id", ondelete="CASCADE"), nullable=True
    )
    block_type: Mapped[str] = mapped_column(String(24), nullable=False)
    blocked_range: Mapped[Any] = mapped_column(TSTZRANGE, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Resource(UUIDTimestampMixin, Base):
    __tablename__ = "resources"
    __table_args__ = (
        CheckConstraint(
            "resource_type IN ('BARBER_CHAIR', 'WASH_STATION', 'VIP_ROOM')",
            name="valid_resource_type",
        ),
        Index("ix_resources_branch_active", "branch_id", "is_active"),
    )

    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False, default="BARBER_CHAIR")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

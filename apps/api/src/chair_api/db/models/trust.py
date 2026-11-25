"""Reviews, private Style Passport, support disputes, notifications, and audit logs."""

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
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from chair_api.db.base import Base, UUIDTimestampMixin


class Review(UUIDTimestampMixin, Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="valid_rating"),
        CheckConstraint("hygiene_rating >= 1 AND hygiene_rating <= 5", name="valid_hygiene_rating"),
        Index("ix_reviews_branch_published", "branch_id", "is_published"),
    )

    booking_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bookings.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    customer_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False
    )
    staff_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff.id", ondelete="SET NULL"), nullable=True
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    hygiene_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class StyleProfile(UUIDTimestampMixin, Base):
    __tablename__ = "style_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    preferred_length: Mapped[str | None] = mapped_column(String(80), nullable=True)
    fade_style: Mapped[str | None] = mapped_column(String(80), nullable=True)
    beard_style: Mapped[str | None] = mapped_column(String(80), nullable=True)
    skin_sensitivity_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    barber_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    share_with_booked_barber: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class StylePhoto(UUIDTimestampMixin, Base):
    __tablename__ = "style_photos"
    __table_args__ = (
        CheckConstraint(
            "angle_label IN ('FRONT', 'LEFT', 'RIGHT', 'BACK')",
            name="valid_style_photo_angle",
        ),
        CheckConstraint("size_bytes > 0", name="positive_style_photo_size"),
        Index("ix_style_photos_profile", "style_profile_id"),
    )

    style_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("style_profiles.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    angle_label: Mapped[str] = mapped_column(String(16), nullable=False, default="FRONT")
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_consents.id", ondelete="SET NULL"), nullable=True
    )
    retention_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SupportCase(UUIDTimestampMixin, Base):
    __tablename__ = "support_cases"
    __table_args__ = (
        CheckConstraint(
            "category IN ('BOOKING_ISSUE', 'HYGIENE_CONCERN', 'PAYMENT_REFUND', "
            "'PARTNER_DISPUTE', 'OTHER')",
            name="valid_support_category",
        ),
        CheckConstraint(
            "priority IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name="valid_support_priority",
        ),
        CheckConstraint(
            "status IN ('OPEN', 'IN_REVIEW', 'ACTION_TAKEN', 'RESOLVED', 'CLOSED')",
            name="valid_support_status",
        ),
        Index("ix_support_cases_status_priority", "status", "priority"),
    )

    case_number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    reporter_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    booking_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="SET NULL"), nullable=True
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="MEDIUM")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="OPEN")
    assigned_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Notification(UUIDTimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(
            "channel IN ('PUSH', 'SMS', 'EMAIL', 'IN_APP')",
            name="valid_notification_channel",
        ),
        CheckConstraint(
            "status IN ('QUEUED', 'SENT', 'FAILED', 'READ')",
            name="valid_notification_status",
        ),
        Index("ix_notifications_user_status", "user_id", "status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    template_key: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="QUEUED")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(UUIDTimestampMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
        Index("ix_audit_logs_branch_created", "branch_id", "created_at"),
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="SET NULL"), nullable=True
    )
    before_state_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after_state_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)

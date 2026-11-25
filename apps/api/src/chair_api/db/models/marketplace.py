"""Marketplace salons, branches, zones, KYC documents, checks, and hygiene inspections."""

import uuid
from datetime import datetime
from typing import Any

from geoalchemy2 import Geography
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


class ServiceZone(UUIDTimestampMixin, Base):
    __tablename__ = "service_zones"

    city: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    boundary: Mapped[Any | None] = mapped_column(
        Geography(geometry_type="POLYGON", srid=4326), nullable=True
    )
    center: Mapped[Any | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Salon(UUIDTimestampMixin, Base):
    __tablename__ = "salons"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'PENDING_REVIEW', 'ACTIVE', 'SUSPENDED')",
            name="valid_salon_status",
        ),
        CheckConstraint(
            "verification_badge_status IN ('UNVERIFIED', 'PENDING', 'VERIFIED', 'SUSPENDED')",
            name="valid_salon_badge_status",
        ),
    )

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    legal_name: Mapped[str] = mapped_column(String(180), nullable=False)
    brand_name: Mapped[str] = mapped_column(String(180), nullable=False)
    gstin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pan_masked: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    verification_badge_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="UNVERIFIED"
    )


class Branch(UUIDTimestampMixin, Base):
    __tablename__ = "branches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'CLOSED', 'SUSPENDED')",
            name="valid_branch_status",
        ),
        CheckConstraint(
            "verification_status IN "
            "('UNVERIFIED', 'PENDING', 'CHAIR_VERIFIED', 'ACTION_REQUIRED', 'SUSPENDED')",
            name="valid_branch_verification_status",
        ),
        Index("ix_branches_location_gist", "location", postgresql_using="gist"),
        Index("ix_branches_salon_status", "salon_id", "status"),
    )

    salon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("salons.id", ondelete="CASCADE"), nullable=False
    )
    zone_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_zones.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)
    address_line1: Mapped[str] = mapped_column(String(255), nullable=False)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(80), nullable=False)
    pincode: Mapped[str] = mapped_column(String(12), nullable=False)
    location: Mapped[Any] = mapped_column(
        Geography(geometry_type="POINT", srid=4326), nullable=False
    )
    operating_hours_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    online_booking_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    featured_disclosure_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="UNVERIFIED"
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")


class SalonDocument(UUIDTimestampMixin, Base):
    __tablename__ = "salon_documents"
    __table_args__ = (
        CheckConstraint(
            "document_type IN ('OWNER_ID', 'BUSINESS_REGISTRATION', "
            "'SHOP_ESTABLISHMENT_LICENSE', 'MUNICIPAL_TRADE_LICENSE', "
            "'ADDRESS_PROOF', 'BANK_PROOF')",
            name="valid_document_type",
        ),
        CheckConstraint(
            "review_status IN ('PENDING', 'APPROVED', 'REJECTED')",
            name="valid_document_review_status",
        ),
        CheckConstraint("size_bytes > 0", name="positive_document_size"),
        Index("ix_salon_documents_salon_branch", "salon_id", "branch_id"),
    )

    salon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("salons.id", ondelete="CASCADE"), nullable=False
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=True
    )
    document_type: Mapped[str] = mapped_column(String(48), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256_hex: Mapped[str] = mapped_column(String(64), nullable=False)
    review_status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VerificationCheck(UUIDTimestampMixin, Base):
    __tablename__ = "verification_checks"
    __table_args__ = (
        CheckConstraint(
            "check_type IN ('IDENTITY', 'BUSINESS', 'ADDRESS', 'LOCAL_LICENSE', "
            "'BANK_PENNY_DROP', 'PHYSICAL_INSPECTION')",
            name="valid_verification_check_type",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'PASSED', 'FAILED', 'EXPIRED')",
            name="valid_verification_check_status",
        ),
        Index("ix_verification_checks_salon_branch", "salon_id", "branch_id"),
    )

    salon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("salons.id", ondelete="CASCADE"), nullable=False
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=True
    )
    check_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Inspection(UUIDTimestampMixin, Base):
    __tablename__ = "inspections"
    __table_args__ = (
        CheckConstraint(
            "numerical_score >= 0 AND numerical_score <= 100", name="valid_score_range"
        ),
        CheckConstraint(
            "overall_outcome IN "
            "('SCHEDULED', 'PASSED', 'CORRECTIVE_ACTION_REQUIRED', 'FAILED_CRITICAL')",
            name="valid_inspection_outcome",
        ),
        CheckConstraint(
            "overall_outcome = 'SCHEDULED' OR ("
            "(single_use_blades_ok AND sharps_disposal_ok AND "
            "instrument_disinfection_ok AND fresh_towels_ok) "
            "OR overall_outcome = 'FAILED_CRITICAL')",
            name="critical_hygiene_failure_override",
        ),
        Index("ix_inspections_branch_completed", "branch_id", "completed_at"),
    )

    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False
    )
    inspector_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    numerical_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    single_use_blades_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sharps_disposal_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    instrument_disinfection_ok: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    fresh_towels_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    overall_outcome: Mapped[str] = mapped_column(String(40), nullable=False, default="SCHEDULED")
    corrective_action_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reinspection_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    evidence_keys_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

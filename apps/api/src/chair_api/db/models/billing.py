"""Payments, webhook events, refunds, settlements, commissions, and SaaS plans."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from chair_api.db.base import Base, UUIDTimestampMixin


class SubscriptionPlan(UUIDTimestampMixin, Base):
    __tablename__ = "subscription_plans"
    __table_args__ = (
        CheckConstraint("monthly_price_paise >= 0", name="non_negative_plan_price"),
        CheckConstraint(
            "commission_rate_bps >= 0 AND commission_rate_bps <= 10000",
            name="valid_commission_bps",
        ),
    )

    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    monthly_price_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    commission_rate_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Payment(UUIDTimestampMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('PAY_AT_SALON', 'TEST_MODE', 'RAZORPAY')",
            name="valid_payment_provider",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'AUTHORIZED', 'CAPTURED', 'FAILED', "
            "'REFUND_PENDING', 'REFUNDED', 'PAY_AT_SALON')",
            name="valid_payment_status",
        ),
        CheckConstraint("amount_paise >= 0", name="non_negative_payment_amount"),
        Index("ix_payments_booking_id", "booking_id"),
    )

    booking_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PaymentEvent(UUIDTimestampMixin, Base):
    __tablename__ = "payment_events"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_provider_event_id"),
    )

    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    signature_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_error: Mapped[str | None] = mapped_column(String(500), nullable=True)


class Refund(UUIDTimestampMixin, Base):
    __tablename__ = "refunds"
    __table_args__ = (
        CheckConstraint(
            "reason IN ('CUSTOMER_CANCELLED', 'PARTNER_CANCELLED', "
            "'LATE_PAYMENT_HOLD_EXPIRED', 'DISPUTE_RESOLUTION')",
            name="valid_refund_reason",
        ),
        CheckConstraint("status IN ('PENDING', 'PROCESSED', 'FAILED')", name="valid_refund_status"),
        CheckConstraint("amount_paise > 0", name="positive_refund_amount"),
    )

    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False
    )
    booking_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False
    )
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(48), nullable=False)
    provider_refund_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    initiated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Settlement(UUIDTimestampMixin, Base):
    __tablename__ = "settlements"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'SETTLED', 'FAILED')",
            name="valid_settlement_status",
        ),
        CheckConstraint("gross_paise >= 0", name="non_negative_settlement_gross"),
        CheckConstraint("commission_paise >= 0", name="non_negative_settlement_commission"),
        CheckConstraint("tax_tds_paise >= 0", name="non_negative_settlement_tds"),
        Index("ix_settlements_branch_period", "branch_id", "period_start", "period_end"),
    )

    salon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("salons.id", ondelete="RESTRICT"), nullable=False
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    gross_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    commission_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_tds_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    net_payout_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payout_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")


class CommissionLedger(UUIDTimestampMixin, Base):
    __tablename__ = "commission_ledger"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACCRUED', 'SETTLED', 'REVERSED')",
            name="valid_commission_status",
        ),
        CheckConstraint("gross_booking_paise >= 0", name="non_negative_gross_booking_paise"),
        CheckConstraint("commission_paise >= 0", name="non_negative_commission_paise"),
        CheckConstraint("gst_on_commission_paise >= 0", name="non_negative_gst_paise"),
        Index("ix_commission_ledger_branch_status", "branch_id", "status"),
    )

    booking_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bookings.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    salon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("salons.id", ondelete="RESTRICT"), nullable=False
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    gross_booking_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    commission_rate_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    commission_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    gst_on_commission_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    eligibility_reason: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACCRUED")
    settlement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("settlements.id", ondelete="SET NULL"), nullable=True
    )


class Subscription(UUIDTimestampMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('TRIAL', 'ACTIVE', 'PAST_DUE', 'CANCELLED')",
            name="valid_subscription_status",
        ),
        Index("ix_subscriptions_branch_status", "branch_id", "status"),
    )

    salon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("salons.id", ondelete="CASCADE"), nullable=False
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscription_plans.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class SubscriptionInvoice(UUIDTimestampMixin, Base):
    __tablename__ = "subscription_invoices"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'OPEN', 'PAID', 'VOID')",
            name="valid_invoice_status",
        ),
        CheckConstraint("subtotal_paise >= 0", name="non_negative_subtotal_paise"),
        CheckConstraint("gst_paise >= 0", name="non_negative_invoice_gst_paise"),
        CheckConstraint("total_paise >= 0", name="non_negative_invoice_total_paise"),
    )

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False
    )
    invoice_number: Mapped[str] = mapped_column(String(48), nullable=False, unique=True)
    subtotal_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    gst_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    total_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="OPEN")
    provider_invoice_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

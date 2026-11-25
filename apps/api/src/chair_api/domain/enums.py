"""Canonical domain enumerations shared across ORM models, API schemas, and rules."""

from enum import StrEnum


class UserRole(StrEnum):
    CUSTOMER = "CUSTOMER"
    PARTNER_OWNER = "PARTNER_OWNER"
    PARTNER_STAFF = "PARTNER_STAFF"
    ADMIN = "ADMIN"


class ConsentType(StrEnum):
    TERMS = "TERMS"
    PRIVACY_DPDP = "PRIVACY_DPDP"
    MARKETING = "MARKETING"
    LOCATION = "LOCATION"
    STYLE_PASSPORT_PHOTOS = "STYLE_PASSPORT_PHOTOS"


class SalonStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BranchStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    SUSPENDED = "SUSPENDED"


class BranchVerificationStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    PENDING = "PENDING"
    CHAIR_VERIFIED = "CHAIR_VERIFIED"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    SUSPENDED = "SUSPENDED"


class DocumentType(StrEnum):
    OWNER_ID = "OWNER_ID"
    BUSINESS_REGISTRATION = "BUSINESS_REGISTRATION"
    SHOP_ESTABLISHMENT_LICENSE = "SHOP_ESTABLISHMENT_LICENSE"
    MUNICIPAL_TRADE_LICENSE = "MUNICIPAL_TRADE_LICENSE"
    ADDRESS_PROOF = "ADDRESS_PROOF"
    BANK_PROOF = "BANK_PROOF"


class DocumentReviewStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class VerificationCheckType(StrEnum):
    IDENTITY = "IDENTITY"
    BUSINESS = "BUSINESS"
    ADDRESS = "ADDRESS"
    LOCAL_LICENSE = "LOCAL_LICENSE"
    BANK_PENNY_DROP = "BANK_PENNY_DROP"
    PHYSICAL_INSPECTION = "PHYSICAL_INSPECTION"


class VerificationCheckStatus(StrEnum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class InspectionOutcome(StrEnum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    CORRECTIVE_ACTION_REQUIRED = "CORRECTIVE_ACTION_REQUIRED"
    FAILED_CRITICAL = "FAILED_CRITICAL"


class ServiceCategory(StrEnum):
    HAIRCUT = "HAIRCUT"
    BEARD = "BEARD"
    SHAVE = "SHAVE"
    FACIAL = "FACIAL"
    PACKAGE = "PACKAGE"
    COLOR = "COLOR"


class StaffStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    INACTIVE = "INACTIVE"


class ScheduleBlockType(StrEnum):
    BREAK = "BREAK"
    LEAVE = "LEAVE"
    HOLIDAY = "HOLIDAY"
    MAINTENANCE = "MAINTENANCE"


class ResourceType(StrEnum):
    BARBER_CHAIR = "BARBER_CHAIR"
    WASH_STATION = "WASH_STATION"
    VIP_ROOM = "VIP_ROOM"


class BookingSource(StrEnum):
    PLATFORM = "PLATFORM"
    WALK_IN = "WALK_IN"


class BookingMode(StrEnum):
    INSTANT = "INSTANT"
    REQUEST = "REQUEST"


class BookingStatus(StrEnum):
    HELD = "HELD"
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    IN_SERVICE = "IN_SERVICE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    NO_SHOW = "NO_SHOW"


class SlotHoldStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CONVERTED = "CONVERTED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class WalkInStatus(StrEnum):
    WAITING = "WAITING"
    SEATED = "SEATED"
    IN_SERVICE = "IN_SERVICE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class PaymentProviderName(StrEnum):
    PAY_AT_SALON = "PAY_AT_SALON"
    TEST_MODE = "TEST_MODE"
    RAZORPAY = "RAZORPAY"


class PaymentStatus(StrEnum):
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    FAILED = "FAILED"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"
    PAY_AT_SALON = "PAY_AT_SALON"


class RefundReason(StrEnum):
    CUSTOMER_CANCELLED = "CUSTOMER_CANCELLED"
    PARTNER_CANCELLED = "PARTNER_CANCELLED"
    LATE_PAYMENT_HOLD_EXPIRED = "LATE_PAYMENT_HOLD_EXPIRED"
    DISPUTE_RESOLUTION = "DISPUTE_RESOLUTION"


class RefundStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class SettlementStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SETTLED = "SETTLED"
    FAILED = "FAILED"


class CommissionStatus(StrEnum):
    ACCRUED = "ACCRUED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class SubscriptionStatus(StrEnum):
    TRIAL = "TRIAL"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"


class InvoiceStatus(StrEnum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    PAID = "PAID"
    VOID = "VOID"


class SupportCategory(StrEnum):
    BOOKING_ISSUE = "BOOKING_ISSUE"
    HYGIENE_CONCERN = "HYGIENE_CONCERN"
    PAYMENT_REFUND = "PAYMENT_REFUND"
    PARTNER_DISPUTE = "PARTNER_DISPUTE"
    OTHER = "OTHER"


class SupportPriority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SupportStatus(StrEnum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    ACTION_TAKEN = "ACTION_TAKEN"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class NotificationChannel(StrEnum):
    PUSH = "PUSH"
    SMS = "SMS"
    EMAIL = "EMAIL"
    IN_APP = "IN_APP"


class NotificationStatus(StrEnum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    FAILED = "FAILED"
    READ = "READ"

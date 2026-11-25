"""Initial CHAIR schema: 33 core entities, PostGIS geography, and btree_gist constraints.

Revision ID: 20261125_0001
Revises:
Create Date: 2026-11-25 04:32:00+00:00
"""

from collections.abc import Sequence

from alembic import op
import geoalchemy2
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261125_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid_pk() -> sa.Column[sa.UUID]:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )


def _timestamps() -> tuple[sa.Column[sa.DateTime], sa.Column[sa.DateTime]]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist;")

    # 1. users
    op.create_table(
        "users",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("phone_e164", sa.String(length=20), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("full_name", sa.String(length=120), nullable=True),
        sa.Column("preferred_locale", sa.String(length=8), nullable=False, server_default="en"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("preferred_locale IN ('en', 'hi')", name="ck_users_valid_locale"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("phone_e164", name="uq_users_phone_e164"),
    )
    op.create_index("ix_users_phone_e164", "users", ["phone_e164"], unique=False)

    # 2. service_zones
    op.create_table(
        "service_zones",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("city", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "boundary",
            geoalchemy2.types.Geography(
                geometry_type="POLYGON",
                srid=4326,
                from_text="ST_GeogFromText",
                name="geography",
            ),
            nullable=True,
        ),
        sa.Column(
            "center",
            geoalchemy2.types.Geography(
                geometry_type="POINT",
                srid=4326,
                from_text="ST_GeogFromText",
                name="geography",
            ),
            nullable=True,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.PrimaryKeyConstraint("id", name="pk_service_zones"),
    )
    op.create_index("ix_service_zones_city", "service_zones", ["city"], unique=False)

    # 3. services
    op.create_table(
        "services",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name_en", sa.String(length=120), nullable=False),
        sa.Column("name_hi", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("default_duration_minutes", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.CheckConstraint(
            "category IN ('HAIRCUT', 'BEARD', 'SHAVE', 'FACIAL', 'PACKAGE', 'COLOR')",
            name="ck_services_valid_service_category",
        ),
        sa.CheckConstraint(
            "default_duration_minutes > 0",
            name="ck_services_positive_default_duration",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_services"),
        sa.UniqueConstraint("code", name="uq_services_code"),
    )

    # 4. subscription_plans
    op.create_table(
        "subscription_plans",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("monthly_price_paise", sa.Integer(), nullable=False),
        sa.Column("commission_rate_bps", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.CheckConstraint("monthly_price_paise >= 0", name="ck_subscription_plans_non_negative_plan_price"),
        sa.CheckConstraint(
            "commission_rate_bps >= 0 AND commission_rate_bps <= 10000",
            name="ck_subscription_plans_valid_commission_bps",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_subscription_plans"),
        sa.UniqueConstraint("code", name="uq_subscription_plans_code"),
    )

    # 5. idempotency_keys
    op.create_table(
        "idempotency_keys",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("actor_key", sa.String(length=128), nullable=False),
        sa.Column("endpoint", sa.String(length=160), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column(
            "response_body_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_idempotency_keys"),
        sa.UniqueConstraint(
            "actor_key",
            "endpoint",
            "idempotency_key",
            name="uq_actor_endpoint_key",
        ),
    )

    # 6. salons
    op.create_table(
        "salons",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("legal_name", sa.String(length=180), nullable=False),
        sa.Column("brand_name", sa.String(length=180), nullable=False),
        sa.Column("gstin", sa.String(length=20), nullable=True),
        sa.Column("pan_masked", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="DRAFT"),
        sa.Column(
            "verification_badge_status",
            sa.String(length=32),
            nullable=False,
            server_default="UNVERIFIED",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'PENDING_REVIEW', 'ACTIVE', 'SUSPENDED')",
            name="ck_salons_valid_salon_status",
        ),
        sa.CheckConstraint(
            "verification_badge_status IN ('UNVERIFIED', 'PENDING', 'VERIFIED', 'SUSPENDED')",
            name="ck_salons_valid_salon_badge_status",
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_salons"),
    )
    op.create_index("ix_salons_owner_user_id", "salons", ["owner_user_id"], unique=False)

    # 7. branches
    op.create_table(
        "branches",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("salon_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("zone_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("slug", sa.String(length=180), nullable=False),
        sa.Column("address_line1", sa.String(length=255), nullable=False),
        sa.Column("address_line2", sa.String(length=255), nullable=True),
        sa.Column("city", sa.String(length=80), nullable=False),
        sa.Column("state", sa.String(length=80), nullable=False),
        sa.Column("pincode", sa.String(length=12), nullable=False),
        sa.Column(
            "location",
            geoalchemy2.types.Geography(
                geometry_type="POINT",
                srid=4326,
                from_text="ST_GeogFromText",
                name="geography",
            ),
            nullable=False,
        ),
        sa.Column(
            "operating_hours_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "online_booking_paused",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("featured_disclosure_label", sa.String(length=80), nullable=True),
        sa.Column(
            "verification_status",
            sa.String(length=32),
            nullable=False,
            server_default="UNVERIFIED",
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="DRAFT"),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'CLOSED', 'SUSPENDED')",
            name="ck_branches_valid_branch_status",
        ),
        sa.CheckConstraint(
            "verification_status IN "
            "('UNVERIFIED', 'PENDING', 'CHAIR_VERIFIED', 'ACTION_REQUIRED', 'SUSPENDED')",
            name="ck_branches_valid_branch_verification_status",
        ),
        sa.ForeignKeyConstraint(["salon_id"], ["salons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["zone_id"], ["service_zones.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_branches"),
        sa.UniqueConstraint("slug", name="uq_branches_slug"),
    )
    op.create_index("ix_branches_city", "branches", ["city"], unique=False)
    op.create_index(
        "ix_branches_location_gist", "branches", ["location"], unique=False, postgresql_using="gist"
    )
    op.create_index("ix_branches_salon_status", "branches", ["salon_id", "status"], unique=False)

    # 8. user_roles
    op.create_table(
        "user_roles",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("salon_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('CUSTOMER', 'PARTNER_OWNER', 'PARTNER_STAFF', 'ADMIN')",
            name="ck_user_roles_valid_user_role",
        ),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["salon_id"], ["salons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_user_roles"),
        sa.UniqueConstraint("user_id", "role", "salon_id", "branch_id", name="uq_role_scope"),
    )
    op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"], unique=False)

    # 9. user_consents
    op.create_table(
        "user_consents",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("consent_type", sa.String(length=40), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.CheckConstraint(
            "consent_type IN ('TERMS', 'PRIVACY_DPDP', 'MARKETING', "
            "'LOCATION', 'STYLE_PASSPORT_PHOTOS')",
            name="ck_user_consents_valid_consent_type",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_user_consents"),
    )
    op.create_index(
        "ix_user_consents_user_type", "user_consents", ["user_id", "consent_type"], unique=False
    )

    # 10. salon_documents
    op.create_table(
        "salon_documents",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("salon_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_type", sa.String(length=48), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256_hex", sa.String(length=64), nullable=False),
        sa.Column("review_status", sa.String(length=24), nullable=False, server_default="PENDING"),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "document_type IN ('OWNER_ID', 'BUSINESS_REGISTRATION', "
            "'SHOP_ESTABLISHMENT_LICENSE', 'MUNICIPAL_TRADE_LICENSE', "
            "'ADDRESS_PROOF', 'BANK_PROOF')",
            name="ck_salon_documents_valid_document_type",
        ),
        sa.CheckConstraint(
            "review_status IN ('PENDING', 'APPROVED', 'REJECTED')",
            name="ck_salon_documents_valid_document_review_status",
        ),
        sa.CheckConstraint("size_bytes > 0", name="ck_salon_documents_positive_document_size"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["salon_id"], ["salons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_salon_documents"),
    )
    op.create_index(
        "ix_salon_documents_salon_branch", "salon_documents", ["salon_id", "branch_id"], unique=False
    )

    # 11. verification_checks
    op.create_table(
        "verification_checks",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("salon_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("check_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="PENDING"),
        sa.Column("verified_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "check_type IN ('IDENTITY', 'BUSINESS', 'ADDRESS', 'LOCAL_LICENSE', "
            "'BANK_PENNY_DROP', 'PHYSICAL_INSPECTION')",
            name="ck_verification_checks_valid_verification_check_type",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PASSED', 'FAILED', 'EXPIRED')",
            name="ck_verification_checks_valid_verification_check_status",
        ),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["salon_id"], ["salons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["verified_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_verification_checks"),
    )
    op.create_index(
        "ix_verification_checks_salon_branch",
        "verification_checks",
        ["salon_id", "branch_id"],
        unique=False,
    )

    # 12. inspections
    op.create_table(
        "inspections",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("inspector_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("numerical_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "single_use_blades_ok", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "sharps_disposal_ok", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "instrument_disinfection_ok",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("fresh_towels_ok", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("overall_outcome", sa.String(length=40), nullable=False, server_default="SCHEDULED"),
        sa.Column("corrective_action_notes", sa.Text(), nullable=True),
        sa.Column("reinspection_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "evidence_keys_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.CheckConstraint(
            "numerical_score >= 0 AND numerical_score <= 100",
            name="ck_inspections_valid_score_range",
        ),
        sa.CheckConstraint(
            "overall_outcome IN "
            "('SCHEDULED', 'PASSED', 'CORRECTIVE_ACTION_REQUIRED', 'FAILED_CRITICAL')",
            name="ck_inspections_valid_inspection_outcome",
        ),
        sa.CheckConstraint(
            "overall_outcome = 'SCHEDULED' OR ("
            "(single_use_blades_ok AND sharps_disposal_ok AND "
            "instrument_disinfection_ok AND fresh_towels_ok) "
            "OR overall_outcome = 'FAILED_CRITICAL')",
            name="ck_inspections_critical_hygiene_failure_override",
        ),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["inspector_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_inspections"),
    )
    op.create_index(
        "ix_inspections_branch_completed",
        "inspections",
        ["branch_id", "completed_at"],
        unique=False,
    )

    # 13. branch_services
    op.create_table(
        "branch_services",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_name_en", sa.String(length=140), nullable=False),
        sa.Column("display_name_hi", sa.String(length=140), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price_paise", sa.Integer(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("buffer_before_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("buffer_after_minutes", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.CheckConstraint("price_paise >= 0", name="ck_branch_services_non_negative_price_paise"),
        sa.CheckConstraint("duration_minutes > 0", name="ck_branch_services_positive_duration_minutes"),
        sa.CheckConstraint(
            "buffer_before_minutes >= 0", name="ck_branch_services_non_negative_buffer_before"
        ),
        sa.CheckConstraint(
            "buffer_after_minutes >= 0", name="ck_branch_services_non_negative_buffer_after"
        ),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_branch_services"),
        sa.UniqueConstraint("branch_id", "service_id", name="uq_branch_service"),
    )
    op.create_index(
        "ix_branch_services_branch_active",
        "branch_services",
        ["branch_id", "is_active"],
        unique=False,
    )

    # 14. staff
    op.create_table(
        "staff",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column(
            "specializations_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "portfolio_keys_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("is_verified_staff", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "is_accepting_bookings", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="ACTIVE"),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'ON_LEAVE', 'INACTIVE')",
            name="ck_staff_valid_staff_status",
        ),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_staff"),
    )
    op.create_index("ix_staff_branch_status", "staff", ["branch_id", "status"], unique=False)

    # 15. staff_services
    op.create_table(
        "staff_services",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("staff_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_service_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("custom_duration_minutes", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.CheckConstraint(
            "custom_duration_minutes IS NULL OR custom_duration_minutes > 0",
            name="ck_staff_services_positive_custom_duration",
        ),
        sa.ForeignKeyConstraint(["branch_service_id"], ["branch_services.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["staff_id"], ["staff.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_staff_services"),
        sa.UniqueConstraint("staff_id", "branch_service_id", name="uq_staff_branch_service"),
    )

    # 16. staff_shifts
    op.create_table(
        "staff_shifts",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("staff_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("start_time_local", sa.Time(), nullable=False),
        sa.Column("end_time_local", sa.Time(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Asia/Kolkata"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_staff_shifts_valid_weekday"),
        sa.CheckConstraint(
            "end_time_local > start_time_local", name="ck_staff_shifts_valid_shift_window"
        ),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["staff_id"], ["staff.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_staff_shifts"),
    )
    op.create_index(
        "ix_staff_shifts_staff_weekday", "staff_shifts", ["staff_id", "weekday"], unique=False
    )

    # 17. schedule_blocks
    op.create_table(
        "schedule_blocks",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("staff_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("block_type", sa.String(length=24), nullable=False),
        sa.Column("blocked_range", postgresql.TSTZRANGE(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.CheckConstraint(
            "block_type IN ('BREAK', 'LEAVE', 'HOLIDAY', 'MAINTENANCE')",
            name="ck_schedule_blocks_valid_block_type",
        ),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["staff_id"], ["staff.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_schedule_blocks"),
    )
    op.create_index(
        "ix_schedule_blocks_branch_staff", "schedule_blocks", ["branch_id", "staff_id"], unique=False
    )

    # 18. resources
    op.create_table(
        "resources",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column(
            "resource_type", sa.String(length=32), nullable=False, server_default="BARBER_CHAIR"
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.CheckConstraint(
            "resource_type IN ('BARBER_CHAIR', 'WASH_STATION', 'VIP_ROOM')",
            name="ck_resources_valid_resource_type",
        ),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_resources"),
    )
    op.create_index(
        "ix_resources_branch_active", "resources", ["branch_id", "is_active"], unique=False
    )

    # 19. bookings
    op.create_table(
        "bookings",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("booking_code", sa.String(length=24), nullable=False),
        sa.Column("customer_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="PLATFORM"),
        sa.Column("booking_mode", sa.String(length=20), nullable=False, server_default="INSTANT"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="HELD"),
        sa.Column("scheduled_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_price_paise", sa.Integer(), nullable=False),
        sa.Column("discount_paise", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("net_payable_paise", sa.Integer(), nullable=False),
        sa.Column(
            "is_featured_attribution", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("check_in_otp_hash", sa.String(length=128), nullable=True),
        sa.Column("completion_otp_hash", sa.String(length=128), nullable=True),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("cancelled_by_role", sa.String(length=32), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint("source IN ('PLATFORM', 'WALK_IN')", name="ck_bookings_valid_booking_source"),
        sa.CheckConstraint("booking_mode IN ('INSTANT', 'REQUEST')", name="ck_bookings_valid_booking_mode"),
        sa.CheckConstraint(
            "status IN ('HELD', 'REQUESTED', 'CONFIRMED', 'CHECKED_IN', "
            "'IN_SERVICE', 'COMPLETED', 'CANCELLED', 'EXPIRED', 'NO_SHOW')",
            name="ck_bookings_valid_booking_status",
        ),
        sa.CheckConstraint("total_price_paise >= 0", name="ck_bookings_non_negative_total_price"),
        sa.CheckConstraint("discount_paise >= 0", name="ck_bookings_non_negative_discount"),
        sa.CheckConstraint("net_payable_paise >= 0", name="ck_bookings_non_negative_net_payable"),
        sa.CheckConstraint(
            "scheduled_end_at > scheduled_start_at", name="ck_bookings_valid_booking_window"
        ),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_bookings"),
        sa.UniqueConstraint("booking_code", name="uq_bookings_booking_code"),
    )
    op.create_index(
        "ix_bookings_branch_start", "bookings", ["branch_id", "scheduled_start_at"], unique=False
    )
    op.create_index(
        "ix_bookings_customer_created", "bookings", ["customer_user_id", "created_at"], unique=False
    )

    # 20. booking_items
    op.create_table(
        "booking_items",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("booking_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_service_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("service_name_snapshot", sa.String(length=160), nullable=False),
        sa.Column("category_snapshot", sa.String(length=32), nullable=False),
        sa.Column("unit_price_paise_snapshot", sa.Integer(), nullable=False),
        sa.Column("duration_minutes_snapshot", sa.Integer(), nullable=False),
        sa.Column(
            "buffer_before_minutes_snapshot", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "buffer_after_minutes_snapshot", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "unit_price_paise_snapshot >= 0", name="ck_booking_items_non_negative_snapshot_price"
        ),
        sa.CheckConstraint(
            "duration_minutes_snapshot > 0", name="ck_booking_items_positive_snapshot_duration"
        ),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["branch_service_id"], ["branch_services.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_booking_items"),
    )
    op.create_index("ix_booking_items_booking_id", "booking_items", ["booking_id"], unique=False)

    # 21. walk_ins
    op.create_table(
        "walk_ins",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("staff_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("customer_name", sa.String(length=120), nullable=False),
        sa.Column("customer_phone_e164", sa.String(length=20), nullable=True),
        sa.Column("customer_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("service_summary", sa.String(length=255), nullable=False),
        sa.Column("quoted_price_paise", sa.Integer(), nullable=False),
        sa.Column("estimated_duration_minutes", sa.Integer(), nullable=False),
        sa.Column("queue_position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="WAITING"),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('WAITING', 'SEATED', 'IN_SERVICE', 'COMPLETED', 'CANCELLED', 'NO_SHOW')",
            name="ck_walk_ins_valid_walk_in_status",
        ),
        sa.CheckConstraint(
            "quoted_price_paise >= 0", name="ck_walk_ins_non_negative_walk_in_price"
        ),
        sa.CheckConstraint(
            "estimated_duration_minutes > 0", name="ck_walk_ins_positive_walk_in_duration"
        ),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["staff_id"], ["staff.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_walk_ins"),
    )
    op.create_index("ix_walk_ins_branch_status", "walk_ins", ["branch_id", "status"], unique=False)

    # 22. booking_allocations (authoritative anti-double-booking exclusion constraints)
    op.create_table(
        "booking_allocations",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("booking_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("walk_in_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("staff_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("allocated_range", postgresql.TSTZRANGE(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.CheckConstraint(
            "booking_id IS NOT NULL OR walk_in_id IS NOT NULL",
            name="ck_booking_allocations_allocation_has_owner",
        ),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["staff_id"], ["staff.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["walk_in_id"], ["walk_ins.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_booking_allocations"),
        postgresql.ExcludeConstraint(
            (sa.column("staff_id"), "="),
            (sa.column("allocated_range"), "&&"),
            name="uq_active_staff_allocation",
            using="gist",
            where=sa.text("is_active = true"),
        ),
        postgresql.ExcludeConstraint(
            (sa.column("resource_id"), "="),
            (sa.column("allocated_range"), "&&"),
            name="uq_active_resource_allocation",
            using="gist",
            where=sa.text("is_active = true AND resource_id IS NOT NULL"),
        ),
    )
    op.create_index(
        "ix_booking_allocations_branch", "booking_allocations", ["branch_id"], unique=False
    )

    # 23. slot_holds (authoritative temporary hold exclusion constraints)
    op.create_table(
        "slot_holds",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("customer_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("staff_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("hold_range", postgresql.TSTZRANGE(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="ACTIVE"),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'CONVERTED', 'RELEASED', 'EXPIRED')",
            name="ck_slot_holds_valid_slot_hold_status",
        ),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["staff_id"], ["staff.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_slot_holds"),
        postgresql.ExcludeConstraint(
            (sa.column("staff_id"), "="),
            (sa.column("hold_range"), "&&"),
            name="uq_active_staff_hold",
            using="gist",
            where=sa.text("status = 'ACTIVE'"),
        ),
        postgresql.ExcludeConstraint(
            (sa.column("resource_id"), "="),
            (sa.column("hold_range"), "&&"),
            name="uq_active_resource_hold",
            using="gist",
            where=sa.text("status = 'ACTIVE' AND resource_id IS NOT NULL"),
        ),
    )
    op.create_index(
        "ix_slot_holds_expires_status", "slot_holds", ["expires_at", "status"], unique=False
    )

    # 24. payments
    op.create_table(
        "payments",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("booking_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_order_id", sa.String(length=128), nullable=True),
        sa.Column("provider_payment_id", sa.String(length=128), nullable=True),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="INR"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="PENDING"),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "provider IN ('PAY_AT_SALON', 'TEST_MODE', 'RAZORPAY')",
            name="ck_payments_valid_payment_provider",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'AUTHORIZED', 'CAPTURED', 'FAILED', "
            "'REFUND_PENDING', 'REFUNDED', 'PAY_AT_SALON')",
            name="ck_payments_valid_payment_status",
        ),
        sa.CheckConstraint("amount_paise >= 0", name="ck_payments_non_negative_payment_amount"),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_payments"),
    )
    op.create_index("ix_payments_booking_id", "payments", ["booking_id"], unique=False)
    op.create_index("ix_payments_provider_order_id", "payments", ["provider_order_id"], unique=False)
    op.create_index("ix_payments_provider_payment_id", "payments", ["provider_payment_id"], unique=False)

    # 25. payment_events
    op.create_table(
        "payment_events",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_event_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column(
            "signature_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_error", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_payment_events"),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_provider_event_id"),
    )

    # 26. refunds
    op.create_table(
        "refunds",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("booking_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=48), nullable=False),
        sa.Column("provider_refund_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="PENDING"),
        sa.Column("initiated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "reason IN ('CUSTOMER_CANCELLED', 'PARTNER_CANCELLED', "
            "'LATE_PAYMENT_HOLD_EXPIRED', 'DISPUTE_RESOLUTION')",
            name="ck_refunds_valid_refund_reason",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PROCESSED', 'FAILED')", name="ck_refunds_valid_refund_status"
        ),
        sa.CheckConstraint("amount_paise > 0", name="ck_refunds_positive_refund_amount"),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["initiated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_refunds"),
    )

    # 27. settlements
    op.create_table(
        "settlements",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("salon_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gross_paise", sa.BigInteger(), nullable=False),
        sa.Column("commission_paise", sa.BigInteger(), nullable=False),
        sa.Column("tax_tds_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("net_payout_paise", sa.BigInteger(), nullable=False),
        sa.Column("payout_reference", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="PENDING"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'SETTLED', 'FAILED')",
            name="ck_settlements_valid_settlement_status",
        ),
        sa.CheckConstraint("gross_paise >= 0", name="ck_settlements_non_negative_settlement_gross"),
        sa.CheckConstraint(
            "commission_paise >= 0", name="ck_settlements_non_negative_settlement_commission"
        ),
        sa.CheckConstraint("tax_tds_paise >= 0", name="ck_settlements_non_negative_settlement_tds"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["salon_id"], ["salons.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_settlements"),
    )
    op.create_index(
        "ix_settlements_branch_period",
        "settlements",
        ["branch_id", "period_start", "period_end"],
        unique=False,
    )

    # 28. commission_ledger
    op.create_table(
        "commission_ledger",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("booking_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("salon_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gross_booking_paise", sa.Integer(), nullable=False),
        sa.Column("commission_rate_bps", sa.Integer(), nullable=False),
        sa.Column("commission_paise", sa.Integer(), nullable=False),
        sa.Column("gst_on_commission_paise", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("eligibility_reason", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="ACCRUED"),
        sa.Column("settlement_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('ACCRUED', 'SETTLED', 'REVERSED')",
            name="ck_commission_ledger_valid_commission_status",
        ),
        sa.CheckConstraint(
            "gross_booking_paise >= 0", name="ck_commission_ledger_non_negative_gross_booking_paise"
        ),
        sa.CheckConstraint(
            "commission_paise >= 0", name="ck_commission_ledger_non_negative_commission_paise"
        ),
        sa.CheckConstraint(
            "gst_on_commission_paise >= 0", name="ck_commission_ledger_non_negative_gst_paise"
        ),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["salon_id"], ["salons.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["settlement_id"], ["settlements.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_commission_ledger"),
        sa.UniqueConstraint("booking_id", name="uq_commission_ledger_booking_id"),
    )
    op.create_index(
        "ix_commission_ledger_branch_status",
        "commission_ledger",
        ["branch_id", "status"],
        unique=False,
    )

    # 29. subscriptions
    op.create_table(
        "subscriptions",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("salon_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="ACTIVE"),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.CheckConstraint(
            "status IN ('TRIAL', 'ACTIVE', 'PAST_DUE', 'CANCELLED')",
            name="ck_subscriptions_valid_subscription_status",
        ),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["subscription_plans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["salon_id"], ["salons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_subscriptions"),
    )
    op.create_index(
        "ix_subscriptions_branch_status", "subscriptions", ["branch_id", "status"], unique=False
    )

    # 30. subscription_invoices
    op.create_table(
        "subscription_invoices",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invoice_number", sa.String(length=48), nullable=False),
        sa.Column("subtotal_paise", sa.Integer(), nullable=False),
        sa.Column("gst_paise", sa.Integer(), nullable=False),
        sa.Column("total_paise", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="OPEN"),
        sa.Column("provider_invoice_id", sa.String(length=128), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'OPEN', 'PAID', 'VOID')",
            name="ck_subscription_invoices_valid_invoice_status",
        ),
        sa.CheckConstraint(
            "subtotal_paise >= 0", name="ck_subscription_invoices_non_negative_subtotal_paise"
        ),
        sa.CheckConstraint(
            "gst_paise >= 0", name="ck_subscription_invoices_non_negative_invoice_gst_paise"
        ),
        sa.CheckConstraint(
            "total_paise >= 0", name="ck_subscription_invoices_non_negative_invoice_total_paise"
        ),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_subscription_invoices"),
        sa.UniqueConstraint("invoice_number", name="uq_subscription_invoices_invoice_number"),
    )

    # 31. reviews
    op.create_table(
        "reviews",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("booking_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("staff_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("hygiene_rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_reviews_valid_rating"),
        sa.CheckConstraint(
            "hygiene_rating >= 1 AND hygiene_rating <= 5", name="ck_reviews_valid_hygiene_rating"
        ),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["staff_id"], ["staff.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_reviews"),
        sa.UniqueConstraint("booking_id", name="uq_reviews_booking_id"),
    )
    op.create_index(
        "ix_reviews_branch_published", "reviews", ["branch_id", "is_published"], unique=False
    )

    # 32. style_profiles
    op.create_table(
        "style_profiles",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("preferred_length", sa.String(length=80), nullable=True),
        sa.Column("fade_style", sa.String(length=80), nullable=True),
        sa.Column("beard_style", sa.String(length=80), nullable=True),
        sa.Column("skin_sensitivity_notes", sa.Text(), nullable=True),
        sa.Column("barber_notes", sa.Text(), nullable=True),
        sa.Column(
            "share_with_booked_barber", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_style_profiles"),
        sa.UniqueConstraint("user_id", name="uq_style_profiles_user_id"),
    )

    # 33. style_photos
    op.create_table(
        "style_photos",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("style_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("angle_label", sa.String(length=16), nullable=False, server_default="FRONT"),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "angle_label IN ('FRONT', 'LEFT', 'RIGHT', 'BACK')",
            name="ck_style_photos_valid_style_photo_angle",
        ),
        sa.CheckConstraint("size_bytes > 0", name="ck_style_photos_positive_style_photo_size"),
        sa.ForeignKeyConstraint(["consent_id"], ["user_consents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["style_profile_id"], ["style_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_style_photos"),
    )
    op.create_index("ix_style_photos_profile", "style_photos", ["style_profile_id"], unique=False)

    # 34. support_cases
    op.create_table(
        "support_cases",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("case_number", sa.String(length=32), nullable=False),
        sa.Column("reporter_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("booking_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="MEDIUM"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="OPEN"),
        sa.Column("assigned_admin_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "category IN ('BOOKING_ISSUE', 'HYGIENE_CONCERN', 'PAYMENT_REFUND', "
            "'PARTNER_DISPUTE', 'OTHER')",
            name="ck_support_cases_valid_support_category",
        ),
        sa.CheckConstraint(
            "priority IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name="ck_support_cases_valid_support_priority",
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'IN_REVIEW', 'ACTION_TAKEN', 'RESOLVED', 'CLOSED')",
            name="ck_support_cases_valid_support_status",
        ),
        sa.ForeignKeyConstraint(["assigned_admin_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reporter_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_support_cases"),
        sa.UniqueConstraint("case_number", name="uq_support_cases_case_number"),
    )
    op.create_index(
        "ix_support_cases_status_priority", "support_cases", ["status", "priority"], unique=False
    )

    # 35. notifications
    op.create_table(
        "notifications",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("template_key", sa.String(length=80), nullable=False),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="QUEUED"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "channel IN ('PUSH', 'SMS', 'EMAIL', 'IN_APP')",
            name="ck_notifications_valid_notification_channel",
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'SENT', 'FAILED', 'READ')",
            name="ck_notifications_valid_notification_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_notifications"),
    )
    op.create_index(
        "ix_notifications_user_status", "notifications", ["user_id", "status"], unique=False
    )

    # 36. audit_logs
    op.create_table(
        "audit_logs",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_role", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("before_state_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_state_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
    )
    op.create_index(
        "ix_audit_logs_branch_created", "audit_logs", ["branch_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_audit_logs_resource", "audit_logs", ["resource_type", "resource_id"], unique=False
    )


def downgrade() -> None:
    tables_reverse = [
        "audit_logs",
        "notifications",
        "support_cases",
        "style_photos",
        "style_profiles",
        "reviews",
        "subscription_invoices",
        "subscriptions",
        "commission_ledger",
        "settlements",
        "refunds",
        "payment_events",
        "payments",
        "slot_holds",
        "booking_allocations",
        "walk_ins",
        "booking_items",
        "bookings",
        "resources",
        "schedule_blocks",
        "staff_shifts",
        "staff_services",
        "staff",
        "branch_services",
        "inspections",
        "verification_checks",
        "salon_documents",
        "user_consents",
        "user_roles",
        "branches",
        "salons",
        "idempotency_keys",
        "subscription_plans",
        "services",
        "service_zones",
        "users",
    ]
    for table_name in tables_reverse:
        op.drop_table(table_name)

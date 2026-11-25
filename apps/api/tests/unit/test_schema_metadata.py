"""Unit tests validating all 36 tables, UUID PKs, UTC timestamps, paise, and GIST."""

from sqlalchemy import BigInteger, DateTime, Integer
from sqlalchemy.dialects.postgresql import UUID, ExcludeConstraint

import chair_api.db.models  # noqa: F401 - register all ORM models
from chair_api.db.base import Base

CORE_33_ENTITIES = {
    "users",
    "user_roles",
    "user_consents",
    "salons",
    "branches",
    "salon_documents",
    "verification_checks",
    "inspections",
    "services",
    "branch_services",
    "staff",
    "staff_services",
    "staff_shifts",
    "schedule_blocks",
    "resources",
    "bookings",
    "booking_items",
    "booking_allocations",
    "slot_holds",
    "walk_ins",
    "payments",
    "payment_events",
    "refunds",
    "settlements",
    "commission_ledger",
    "subscriptions",
    "subscription_invoices",
    "reviews",
    "style_profiles",
    "style_photos",
    "support_cases",
    "notifications",
    "audit_logs",
}

SUPPORTING_TABLES = {"service_zones", "subscription_plans", "idempotency_keys"}


def test_all_33_core_and_supporting_tables_registered() -> None:
    registered = set(Base.metadata.tables.keys())
    missing = (CORE_33_ENTITIES | SUPPORTING_TABLES) - registered
    assert not missing, f"Missing expected tables: {sorted(missing)}"


def test_all_tables_have_uuid_pk_and_utc_timestamps() -> None:
    for table_name, table in Base.metadata.tables.items():
        pk_cols = list(table.primary_key.columns)
        assert len(pk_cols) == 1, f"{table_name} must have single UUID PK"
        assert isinstance(pk_cols[0].type, UUID), f"{table_name}.id must be UUID"

        for ts_col in ("created_at", "updated_at"):
            assert ts_col in table.c, f"{table_name} missing {ts_col}"
            col_type = table.c[ts_col].type
            assert isinstance(col_type, DateTime) and col_type.timezone is True, (
                f"{table_name}.{ts_col} must be TIMESTAMPTZ"
            )


def test_monetary_columns_use_integer_paise() -> None:
    for table_name, table in Base.metadata.tables.items():
        for col in table.columns:
            if "paise" in col.name:
                assert isinstance(col.type, (Integer, BigInteger)), (
                    f"{table_name}.{col.name} must use Integer/BigInteger, got {col.type}"
                )


def test_exclusion_constraints_present_on_allocations_and_holds() -> None:
    alloc_constraints = {
        c.name
        for c in Base.metadata.tables["booking_allocations"].constraints
        if isinstance(c, ExcludeConstraint)
    }
    assert {"uq_active_staff_allocation", "uq_active_resource_allocation"} <= alloc_constraints

    hold_constraints = {
        c.name
        for c in Base.metadata.tables["slot_holds"].constraints
        if isinstance(c, ExcludeConstraint)
    }
    assert {"uq_active_staff_hold", "uq_active_resource_hold"} <= hold_constraints

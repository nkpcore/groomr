"""Idempotent demo seed script for CHAIR local development.

Every seeded user, salon, branch, barber, and inspection is explicitly labeled [DEMO].
"""

import asyncio
import uuid
from datetime import UTC, datetime, time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chair_api.core.config import get_settings
from chair_api.db.models import (
    Branch,
    BranchService,
    Inspection,
    Resource,
    Salon,
    Service,
    Staff,
    StaffService,
    StaffShift,
    SubscriptionPlan,
    User,
    UserRoleAssignment,
)
from chair_api.db.session import create_engine_and_sessionmaker

DEMO_PLANS = [
    ("STARTER", "Starter [DEMO]", 0, 800),
    ("PRO", "Pro [DEMO]", 49900, 600),
    ("GROWTH", "Growth [DEMO]", 99900, 400),
]

DEMO_SERVICES = [
    ("CLASSIC_HAIRCUT", "Classic Haircut", "क्लासिक हेयरकट", "HAIRCUT", 30),
    ("SKIN_FADE", "Skin Fade & Taper", "स्किन फेड और टेपर", "HAIRCUT", 40),
    ("BEARD_SCULPT", "Beard Sculpt & Trim", "दाढ़ी सेटिंग और ट्रिम", "BEARD", 20),
    ("HOT_TOWEL_SHAVE", "Hot Towel Shave", "हॉट टॉवल शेव", "SHAVE", 30),
]

DEMO_HOURS = {
    "mon": {"open": "09:30", "close": "21:30"},
    "tue": {"open": "09:30", "close": "21:30"},
    "wed": {"open": "09:30", "close": "21:30"},
    "thu": {"open": "09:30", "close": "21:30"},
    "fri": {"open": "09:30", "close": "21:30"},
    "sat": {"open": "09:00", "close": "22:00"},
    "sun": {"open": "10:00", "close": "21:00"},
}


async def _get_or_create_user(
    session: AsyncSession, *, phone_e164: str, full_name: str, locale: str = "en"
) -> User:
    existing = await session.scalar(select(User).where(User.phone_e164 == phone_e164))
    if existing is not None:
        return existing
    user = User(phone_e164=phone_e164, full_name=full_name, preferred_locale=locale)
    session.add(user)
    await session.flush()
    return user


async def seed_demo_data(session: AsyncSession) -> dict[str, int]:
    """Insert idempotent [DEMO] plans, catalog services, salons, branches, staff, and chairs."""
    created_counts = {"plans": 0, "services": 0, "branches": 0, "staff": 0, "resources": 0}

    for code, name, price_paise, bps in DEMO_PLANS:
        existing_plan = await session.scalar(
            select(SubscriptionPlan).where(SubscriptionPlan.code == code)
        )
        if existing_plan is None:
            session.add(
                SubscriptionPlan(
                    code=code,
                    name=name,
                    monthly_price_paise=price_paise,
                    commission_rate_bps=bps,
                )
            )
            created_counts["plans"] += 1

    service_map: dict[str, Service] = {}
    for code, name_en, name_hi, category, duration in DEMO_SERVICES:
        svc = await session.scalar(select(Service).where(Service.code == code))
        if svc is None:
            svc = Service(
                code=code,
                name_en=name_en,
                name_hi=name_hi,
                category=category,
                default_duration_minutes=duration,
            )
            session.add(svc)
            await session.flush()
            created_counts["services"] += 1
        service_map[code] = svc

    owner = await _get_or_create_user(
        session, phone_e164="+919000000001", full_name="[DEMO] Vikram Malhotra (Partner)"
    )
    inspector = await _get_or_create_user(
        session, phone_e164="+919000000002", full_name="[DEMO] Arjun Nair (Inspector)"
    )
    customer = await _get_or_create_user(
        session, phone_e164="+919000000003", full_name="[DEMO] Kabir Sharma (Customer)"
    )

    for user, role in (
        (owner, "PARTNER_OWNER"),
        (inspector, "ADMIN"),
        (customer, "CUSTOMER"),
    ):
        role_exists = await session.scalar(
            select(UserRoleAssignment).where(
                UserRoleAssignment.user_id == user.id,
                UserRoleAssignment.role == role,
            )
        )
        if role_exists is None:
            session.add(UserRoleAssignment(user_id=user.id, role=role))

    salon = await session.scalar(
        select(Salon).where(Salon.brand_name == "[DEMO] The Brass Comb Co.")
    )
    if salon is None:
        salon = Salon(
            owner_user_id=owner.id,
            legal_name="[DEMO] Brass Comb Grooming Pvt Ltd",
            brand_name="[DEMO] The Brass Comb Co.",
            status="ACTIVE",
            verification_badge_status="VERIFIED",
        )
        session.add(salon)
        await session.flush()

    owner_role_rows = list(
        await session.scalars(
            select(UserRoleAssignment).where(
                UserRoleAssignment.user_id == owner.id,
                UserRoleAssignment.role == "PARTNER_OWNER",
            )
        )
    )
    if not owner_role_rows:
        session.add(
            UserRoleAssignment(user_id=owner.id, role="PARTNER_OWNER", salon_id=salon.id)
        )
    else:
        for role_row in owner_role_rows:
            if role_row.salon_id is None:
                role_row.salon_id = salon.id

    demo_branches = [
        {
            "slug": "demo-brass-comb-indiranagar",
            "name": "[DEMO] The Brass Comb — Indiranagar",
            "address": "100 Feet Road, Indiranagar",
            "city": "Bengaluru",
            "state": "Karnataka",
            "pincode": "560038",
            "point_wkt": "SRID=4326;POINT(77.6408 12.9784)",
            "verification_status": "CHAIR_VERIFIED",
            "featured": False,
        },
        {
            "slug": "demo-brass-comb-bandra",
            "name": "[DEMO] The Brass Comb — Bandra West",
            "address": "Pali Hill Road, Bandra West",
            "city": "Mumbai",
            "state": "Maharashtra",
            "pincode": "400050",
            "point_wkt": "SRID=4326;POINT(72.8295 19.0607)",
            "verification_status": "PENDING",
            "featured": True,
        },
    ]

    for b_spec in demo_branches:
        existing_branch = await session.scalar(
            select(Branch).where(Branch.slug == str(b_spec["slug"]))
        )
        if existing_branch is not None:
            continue

        branch = Branch(
            salon_id=salon.id,
            name=str(b_spec["name"]),
            slug=str(b_spec["slug"]),
            address_line1=str(b_spec["address"]),
            city=str(b_spec["city"]),
            state=str(b_spec["state"]),
            pincode=str(b_spec["pincode"]),
            location=str(b_spec["point_wkt"]),
            operating_hours_json=DEMO_HOURS,
            is_featured=bool(b_spec["featured"]),
            featured_disclosure_label="Sponsored [DEMO]" if b_spec["featured"] else None,
            verification_status=str(b_spec["verification_status"]),
            status="ACTIVE",
        )
        session.add(branch)
        await session.flush()
        created_counts["branches"] += 1

        branch_service_ids: list[uuid.UUID] = []
        prices = {
            "CLASSIC_HAIRCUT": 49900,
            "SKIN_FADE": 69900,
            "BEARD_SCULPT": 34900,
            "HOT_TOWEL_SHAVE": 44900,
        }
        for code, svc in service_map.items():
            bs = BranchService(
                branch_id=branch.id,
                service_id=svc.id,
                display_name_en=f"{svc.name_en} [DEMO]",
                display_name_hi=svc.name_hi,
                price_paise=prices[code],
                duration_minutes=svc.default_duration_minutes,
                buffer_before_minutes=0,
                buffer_after_minutes=5,
            )
            session.add(bs)
            await session.flush()
            branch_service_ids.append(bs.id)

        for idx, barber_name in enumerate(
            ("[DEMO] Rakesh Verma", "[DEMO] Imran Siddiqui"), start=1
        ):
            barber = Staff(
                branch_id=branch.id,
                display_name=barber_name,
                bio=(
                    "[DEMO] Senior stylist specializing in classic scissor cuts "
                    "and hot towel shaves."
                ),
                specializations_json=["Classic Cuts", "Beard Sculpting"],
                is_verified_staff=b_spec["verification_status"] == "CHAIR_VERIFIED",
            )
            session.add(barber)
            await session.flush()
            created_counts["staff"] += 1

            for bs_id in branch_service_ids:
                session.add(StaffService(staff_id=barber.id, branch_service_id=bs_id))

            for weekday in range(7):
                session.add(
                    StaffShift(
                        staff_id=barber.id,
                        branch_id=branch.id,
                        weekday=weekday,
                        start_time_local=time(10, 0),
                        end_time_local=time(20, 0),
                    )
                )

            chair = Resource(branch_id=branch.id, name=f"Chair {idx}", resource_type="BARBER_CHAIR")
            session.add(chair)
            created_counts["resources"] += 1

        if b_spec["verification_status"] == "CHAIR_VERIFIED":
            now = datetime.now(UTC)
            session.add(
                Inspection(
                    branch_id=branch.id,
                    inspector_user_id=inspector.id,
                    scheduled_at=now,
                    completed_at=now,
                    numerical_score=92,
                    single_use_blades_ok=True,
                    sharps_disposal_ok=True,
                    instrument_disinfection_ok=True,
                    fresh_towels_ok=True,
                    overall_outcome="PASSED",
                    corrective_action_notes="[DEMO] Passed initial hygiene inspection.",
                )
            )

    await session.commit()
    return created_counts


async def main() -> None:
    settings = get_settings()
    if not settings.enable_demo_seed:
        print("ENABLE_DEMO_SEED=false; skipping demo seed.")
        return
    engine, session_factory = create_engine_and_sessionmaker(settings.database_url)
    try:
        async with session_factory() as session:
            summary = await seed_demo_data(session)
            print(f"[DEMO] Seed completed: {summary}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

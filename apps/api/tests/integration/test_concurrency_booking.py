"""Concurrency tests proving PostgreSQL btree_gist prevents overlapping staff/chair bookings."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from chair_api.db.models import (
    Booking,
    BookingAllocation,
    Branch,
    Resource,
    Salon,
    Staff,
    User,
)


async def test_concurrent_staff_and_chair_allocations_cannot_double_book(
    postgres_test_engine: AsyncEngine,
) -> None:
    """Simultaneous transactions trying to book the same barber/chair must allow only one."""
    session_factory = async_sessionmaker(
        postgres_test_engine, expire_on_commit=False, class_=AsyncSession
    )

    async with session_factory() as setup_session:
        owner = User(phone_e164=f"+9198{uuid.uuid4().int % 10**8:08d}", full_name="[DEMO] Owner")
        customer = User(
            phone_e164=f"+9197{uuid.uuid4().int % 10**8:08d}", full_name="[DEMO] Customer"
        )
        setup_session.add_all([owner, customer])
        await setup_session.flush()

        salon = Salon(
            owner_user_id=owner.id,
            legal_name="[DEMO] Concurrency Salon",
            brand_name="[DEMO] Concurrency",
        )
        setup_session.add(salon)
        await setup_session.flush()

        branch = Branch(
            salon_id=salon.id,
            name="[DEMO] Concurrency Branch",
            slug=f"demo-conc-{uuid.uuid4().hex[:8]}",
            address_line1="123 MG Road",
            city="Bengaluru",
            state="Karnataka",
            pincode="560001",
            location="SRID=4326;POINT(77.5946 12.9716)",
            operating_hours_json={},
        )
        setup_session.add(branch)
        await setup_session.flush()

        staff = Staff(branch_id=branch.id, display_name="[DEMO] Barber A")
        chair = Resource(branch_id=branch.id, name="Chair 1")
        setup_session.add_all([staff, chair])
        await setup_session.flush()

        start = datetime.now(UTC) + timedelta(hours=2)
        end = start + timedelta(minutes=30)

        booking_ids: list[uuid.UUID] = []
        for idx in range(5):
            b = Booking(
                booking_code=f"CHR-TEST-{uuid.uuid4().hex[:6].upper()}-{idx}",
                customer_user_id=customer.id,
                branch_id=branch.id,
                scheduled_start_at=start,
                scheduled_end_at=end,
                total_price_paise=50000,
                net_payable_paise=50000,
                status="CONFIRMED",
            )
            setup_session.add(b)
            await setup_session.flush()
            booking_ids.append(b.id)

        await setup_session.commit()

    slot_range = Range(start, end, bounds="[)")

    async def try_allocate(b_id: uuid.UUID) -> bool:
        async with session_factory() as s:
            try:
                s.add(
                    BookingAllocation(
                        booking_id=b_id,
                        branch_id=branch.id,
                        staff_id=staff.id,
                        resource_id=chair.id,
                        allocated_range=slot_range,
                        is_active=True,
                    )
                )
                await s.commit()
                return True
            except IntegrityError:
                await s.rollback()
                return False

    results = await asyncio.gather(*(try_allocate(b_id) for b_id in booking_ids))
    assert results.count(True) == 1
    assert results.count(False) == 4

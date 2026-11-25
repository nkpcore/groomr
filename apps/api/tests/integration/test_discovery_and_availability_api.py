"""Live Postgres+PostGIS integration tests for branch discovery and availability."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from chair_api.core.config import Settings
from chair_api.db.models import (
    Booking,
    BookingAllocation,
    Branch,
    BranchService,
    Resource,
    Salon,
    Service,
    Staff,
    StaffService,
    StaffShift,
    User,
)
from chair_api.main import create_app


@pytest.fixture
async def discovery_client(
    postgres_test_engine: AsyncEngine,
) -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession]]]:
    """Create FastAPI AsyncClient backed by test Postgres+PostGIS."""
    test_redis_url = "redis://localhost:6379/15"
    redis_probe = Redis.from_url(test_redis_url, decode_responses=True, socket_connect_timeout=1.0)
    try:
        await redis_probe.ping()
    except Exception as exc:
        await redis_probe.aclose()
        pytest.skip(f"Redis unavailable ({type(exc).__name__}).")
    await redis_probe.aclose()

    db_url = postgres_test_engine.url.render_as_string(hide_password=False)
    settings = Settings(
        app_env="test",
        secret_key="integration-test-secret-key-at-least-32-bytes",
        database_url=db_url,
        test_database_url=db_url,
        redis_url=test_redis_url,
    )
    app = create_app(settings)
    session_factory = async_sessionmaker(
        postgres_test_engine, expire_on_commit=False, class_=AsyncSession
    )

    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            yield client, session_factory


async def test_postgis_discovery_filters_featured_disclosure_and_live_availability(
    discovery_client: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, session_factory = discovery_client
    owner_phone = f"+9197{uuid.uuid4().int % 10**8:08d}"
    cust_phone = f"+9198{uuid.uuid4().int % 10**8:08d}"

    created_users: list[uuid.UUID] = []
    created_salons: list[uuid.UUID] = []
    created_branches: list[uuid.UUID] = []
    created_services: list[uuid.UUID] = []

    tomorrow_ist = (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(days=1)).date()
    ist_tz = ZoneInfo("Asia/Kolkata")
    hours_all = {
        k: {"open": "09:00", "close": "20:00"}
        for k in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    }

    try:
        async with session_factory() as s:
            owner = User(phone_e164=owner_phone, full_name="[DEMO] Discovery Owner")
            customer = User(phone_e164=cust_phone, full_name="[DEMO] Discovery Customer")
            s.add_all([owner, customer])
            await s.flush()
            created_users.extend([owner.id, customer.id])

            svc = Service(
                code=f"TEST_CUT_{uuid.uuid4().hex[:6]}",
                name_en="Signature Cut",
                name_hi="सिग्नेचर कट",
                category="HAIRCUT",
                default_duration_minutes=30,
            )
            s.add(svc)
            await s.flush()
            created_services.append(svc.id)

            salon_active = Salon(
                owner_user_id=owner.id,
                legal_name="[DEMO] Active Salon Ltd",
                brand_name="[DEMO] Urban Scissors",
                status="ACTIVE",
            )
            salon_draft = Salon(
                owner_user_id=owner.id,
                legal_name="[DEMO] Draft Salon Ltd",
                brand_name="[DEMO] Hidden Draft Salon",
                status="DRAFT",
            )
            s.add_all([salon_active, salon_draft])
            await s.flush()
            created_salons.extend([salon_active.id, salon_draft.id])

            # Close to Indiranagar (77.6408, 12.9784) vs ~15km away Whitefield (77.7500, 12.9698)
            branch_near = Branch(
                salon_id=salon_active.id,
                name="[DEMO] Urban Scissors Near",
                slug=f"demo-near-{uuid.uuid4().hex[:8]}",
                address_line1="100 Feet Road",
                city="Bengaluru",
                state="Karnataka",
                pincode="560038",
                location="SRID=4326;POINT(77.6410 12.9785)",
                operating_hours_json=hours_all,
                verification_status="CHAIR_VERIFIED",
                is_featured=True,
                featured_disclosure_label="Sponsored [DEMO]",
                status="ACTIVE",
            )
            branch_far = Branch(
                salon_id=salon_active.id,
                name="[DEMO] Urban Scissors Far",
                slug=f"demo-far-{uuid.uuid4().hex[:8]}",
                address_line1="Whitefield Main Rd",
                city="Bengaluru",
                state="Karnataka",
                pincode="560066",
                location="SRID=4326;POINT(77.7500 12.9698)",
                operating_hours_json=hours_all,
                verification_status="PENDING",
                status="ACTIVE",
            )
            branch_hidden = Branch(
                salon_id=salon_draft.id,
                name="[DEMO] Hidden Draft Branch",
                slug=f"demo-hidden-{uuid.uuid4().hex[:8]}",
                address_line1="Nowhere",
                city="Bengaluru",
                state="Karnataka",
                pincode="560001",
                location="SRID=4326;POINT(77.6410 12.9785)",
                operating_hours_json=hours_all,
                status="ACTIVE",
            )
            s.add_all([branch_near, branch_far, branch_hidden])
            await s.flush()
            created_branches.extend([branch_near.id, branch_far.id, branch_hidden.id])

            bs_near = BranchService(
                branch_id=branch_near.id,
                service_id=svc.id,
                display_name_en="Signature Cut [DEMO]",
                display_name_hi="सिग्नेचर कट",
                price_paise=49900,
                duration_minutes=30,
                buffer_before_minutes=0,
                buffer_after_minutes=5,
            )
            bs_far = BranchService(
                branch_id=branch_far.id,
                service_id=svc.id,
                display_name_en="Signature Cut [DEMO]",
                display_name_hi="सिग्नेचर कट",
                price_paise=39900,
                duration_minutes=30,
            )
            s.add_all([bs_near, bs_far])
            await s.flush()

            barber = Staff(
                branch_id=branch_near.id,
                display_name="[DEMO] Kabir Barber",
                is_verified_staff=True,
                status="ACTIVE",
            )
            chair = Resource(branch_id=branch_near.id, name="Chair 1")
            s.add_all([barber, chair])
            await s.flush()

            s.add(StaffService(staff_id=barber.id, branch_service_id=bs_near.id))
            s.add(
                StaffShift(
                    staff_id=barber.id,
                    branch_id=branch_near.id,
                    weekday=tomorrow_ist.weekday(),
                    start_time_local=datetime(2026, 1, 1, 10, 0).time(),
                    end_time_local=datetime(2026, 1, 1, 13, 0).time(),
                )
            )

            # Book 10:00 - 11:00 IST on tomorrow_ist -> should exclude 10:00..10:45 slots!
            alloc_start = datetime(
                tomorrow_ist.year, tomorrow_ist.month, tomorrow_ist.day, 10, 0, tzinfo=ist_tz
            ).astimezone(UTC)
            alloc_end = datetime(
                tomorrow_ist.year, tomorrow_ist.month, tomorrow_ist.day, 11, 0, tzinfo=ist_tz
            ).astimezone(UTC)
            booking = Booking(
                booking_code=f"CHR-DISC-{uuid.uuid4().hex[:6].upper()}",
                customer_user_id=customer.id,
                branch_id=branch_near.id,
                scheduled_start_at=alloc_start,
                scheduled_end_at=alloc_end,
                total_price_paise=49900,
                net_payable_paise=49900,
                status="CONFIRMED",
            )
            s.add(booking)
            await s.flush()
            s.add(
                BookingAllocation(
                    booking_id=booking.id,
                    branch_id=branch_near.id,
                    staff_id=barber.id,
                    resource_id=chair.id,
                    allocated_range=Range(alloc_start, alloc_end, bounds="[)"),
                    is_active=True,
                )
            )
            await s.commit()

        # 1. PostGIS 5km search around Indiranagar finds branch_near, excludes branch_far & draft
        list_res = await client.get(
            "/api/v1/branches",
            params={
                "lat": 12.9784,
                "lng": 77.6408,
                "radius_meters": 5000,
                "verified_only": "true",
                "q": "Urban Scissors",
            },
        )
        assert list_res.status_code == 200, list_res.text
        items = list_res.json()["items"]
        assert len(items) == 1
        near_item = items[0]
        assert near_item["id"] == str(branch_near.id)
        assert near_item["is_featured"] is True
        assert near_item["featured_disclosure_label"] == "Sponsored [DEMO]"
        assert near_item["avg_rating"] is None
        assert near_item["review_count"] == 0
        assert near_item["distance_meters"] < 200

        # 2. Branch detail returns full services, staff qualifications, and integer paise prices
        detail_res = await client.get(f"/api/v1/branches/{branch_near.id}")
        assert detail_res.status_code == 200
        detail = detail_res.json()
        assert detail["services"][0]["price_paise"] == 49900
        assert str(bs_near.id) in detail["staff"][0]["qualified_branch_service_ids"]

        # Hidden draft-salon branch cannot be fetched directly
        hidden_res = await client.get(f"/api/v1/branches/{branch_hidden.id}")
        assert hidden_res.status_code == 404

        # Inactive canonical service excludes availability cleanly (422)
        async with session_factory() as s:
            svc_obj = await s.get(Service, svc.id)
            assert svc_obj is not None
            svc_obj.is_active = False
            await s.commit()
        inactive_svc_avail = await client.get(
            f"/api/v1/branches/{branch_near.id}/availability",
            params={"date": tomorrow_ist.isoformat(), "service_ids": [str(bs_near.id)]},
        )
        assert inactive_svc_avail.status_code == 422

        async with session_factory() as s:
            svc_obj = await s.get(Service, svc.id)
            assert svc_obj is not None
            svc_obj.is_active = True
            await s.commit()

        # 3. Live availability excludes 10:00..10:45 IST occupied by BookingAllocation
        avail_res = await client.get(
            f"/api/v1/branches/{branch_near.id}/availability",
            params={"date": tomorrow_ist.isoformat(), "service_ids": [str(bs_near.id)]},
        )
        assert avail_res.status_code == 200, avail_res.text
        slots = avail_res.json()["slots"]
        ist_times = [
            datetime.fromisoformat(sl["start_at"]).astimezone(ist_tz).strftime("%H:%M")
            for sl in slots
        ]
        assert "10:00" not in ist_times
        assert "10:30" not in ist_times
        assert "11:00" in ist_times
    finally:
        async with session_factory() as s:
            for bid in created_branches:
                await s.execute(delete(BookingAllocation).where(BookingAllocation.branch_id == bid))
                await s.execute(delete(Booking).where(Booking.branch_id == bid))
                await s.execute(delete(StaffShift).where(StaffShift.branch_id == bid))
                await s.execute(delete(Staff).where(Staff.branch_id == bid))
                await s.execute(delete(Resource).where(Resource.branch_id == bid))
                await s.execute(delete(BranchService).where(BranchService.branch_id == bid))
                await s.execute(delete(Branch).where(Branch.id == bid))
            for sid in created_salons:
                await s.execute(delete(Salon).where(Salon.id == sid))
            for svid in created_services:
                await s.execute(delete(Service).where(Service.id == svid))
            for uid in created_users:
                await s.execute(delete(User).where(User.id == uid))
            await s.commit()

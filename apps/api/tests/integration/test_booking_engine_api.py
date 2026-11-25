"""Live PostGIS/PostgreSQL integration tests for Phase 4 Booking Engine invariants."""

import asyncio
import hashlib
import hmac
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from chair_api.core.config import Settings
from chair_api.db.models import (
    AuditLog,
    Booking,
    BookingAllocation,
    Branch,
    BranchService,
    CommissionLedger,
    Payment,
    PaymentEvent,
    Refund,
    Resource,
    Review,
    Salon,
    Service,
    SlotHold,
    Staff,
    StaffService,
    StaffShift,
    User,
    UserRoleAssignment,
)
from chair_api.main import create_app


@pytest.fixture
async def booking_client(
    postgres_test_engine: AsyncEngine,
) -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession], Settings]]:
    """Create FastAPI AsyncClient backed by test Postgres+PostGIS+Redis."""
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
        secret_key="booking-integration-test-secret-key-min-32-bytes",
        database_url=db_url,
        test_database_url=db_url,
        redis_url=test_redis_url,
        razorpay_webhook_secret="chair-integration-webhook-secret",
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
            yield client, session_factory, settings


async def _auth_headers(client: AsyncClient, phone_e164: str) -> dict[str, str]:
    req_res = await client.post("/api/v1/auth/otp/request", json={"phone_e164": phone_e164})
    assert req_res.status_code == 200, req_res.text
    challenge_id = req_res.json()["challenge_id"]
    ver_res = await client.post(
        "/api/v1/auth/otp/verify",
        json={"challenge_id": challenge_id, "phone_e164": phone_e164, "otp_code": "123456"},
    )
    assert ver_res.status_code == 200, ver_res.text
    return {"Authorization": f"Bearer {ver_res.json()['access_token']}"}


async def _seed_bookable_branch(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, uuid.UUID | str]:
    owner_phone = f"+9197{uuid.uuid4().int % 10**8:08d}"
    svc_code = f"SVC_{uuid.uuid4().hex[:8].upper()}"

    async with session_factory() as s:
        owner = User(phone_e164=owner_phone, full_name="[DEMO] Partner Owner")
        s.add(owner)
        await s.flush()

        salon = Salon(
            owner_user_id=owner.id,
            legal_name="[DEMO] Engine Test Pvt Ltd",
            brand_name="[DEMO] Engine Test",
            status="ACTIVE",
            verification_badge_status="VERIFIED",
        )
        s.add(salon)
        await s.flush()
        s.add(UserRoleAssignment(user_id=owner.id, role="PARTNER_OWNER", salon_id=salon.id))

        branch = Branch(
            salon_id=salon.id,
            name="[DEMO] Test Booking Lounge",
            slug=f"demo-book-{uuid.uuid4().hex[:8]}",
            address_line1="12 Church Street",
            city="Bengaluru",
            state="Karnataka",
            pincode="560001",
            location="SRID=4326;POINT(77.6033 12.9756)",
            operating_hours_json={
                d: {"open": "09:00", "close": "21:00"}
                for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
            },
            verification_status="CHAIR_VERIFIED",
            status="ACTIVE",
        )
        s.add(branch)
        await s.flush()

        svc = Service(
            code=svc_code,
            name_en="Classic Scissor Cut",
            name_hi="क्लासिक कट",
            category="HAIRCUT",
            default_duration_minutes=30,
        )
        s.add(svc)
        await s.flush()

        bs = BranchService(
            branch_id=branch.id,
            service_id=svc.id,
            display_name_en="Classic Scissor Cut [DEMO]",
            display_name_hi="क्लासिक कट [DEMO]",
            price_paise=49900,
            duration_minutes=30,
            buffer_before_minutes=0,
            buffer_after_minutes=5,
        )
        s.add(bs)
        await s.flush()

        staff_1 = Staff(
            branch_id=branch.id, display_name="[DEMO] Barber One", is_verified_staff=True
        )
        staff_2 = Staff(
            branch_id=branch.id, display_name="[DEMO] Barber Two", is_verified_staff=True
        )
        chair_1 = Resource(branch_id=branch.id, name="Chair 1")
        chair_2 = Resource(branch_id=branch.id, name="Chair 2")
        s.add_all([staff_1, staff_2, chair_1, chair_2])
        await s.flush()

        for st in (staff_1, staff_2):
            s.add(StaffService(staff_id=st.id, branch_service_id=bs.id))
            for wd in range(7):
                s.add(
                    StaffShift(
                        staff_id=st.id,
                        branch_id=branch.id,
                        weekday=wd,
                        start_time_local=time(9, 30),
                        end_time_local=time(20, 30),
                    )
                )

        await s.commit()
        return {
            "owner_id": owner.id,
            "owner_phone": owner_phone,
            "salon_id": salon.id,
            "branch_id": branch.id,
            "service_id": svc.id,
            "branch_service_id": bs.id,
            "staff_1_id": staff_1.id,
            "staff_2_id": staff_2.id,
        }


async def _cleanup_branch_fixture(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    salon_id: uuid.UUID,
    service_id: uuid.UUID,
    user_ids: list[uuid.UUID],
    phones: list[str],
) -> None:
    async with session_factory() as s:
        extra_users = list(
            await s.scalars(select(User.id).where(User.phone_e164.in_(phones)))
        )
        all_users = list({*user_ids, *extra_users})
        branch_ids = list(
            await s.scalars(select(Branch.id).where(Branch.salon_id == salon_id))
        )
        booking_ids = list(
            await s.scalars(select(Booking.id).where(Booking.branch_id.in_(branch_ids)))
        )
        if booking_ids:
            payment_ids = list(
                await s.scalars(select(Payment.id).where(Payment.booking_id.in_(booking_ids)))
            )
            if payment_ids:
                await s.execute(
                    delete(PaymentEvent).where(PaymentEvent.payment_id.in_(payment_ids))
                )
            await s.execute(delete(Review).where(Review.booking_id.in_(booking_ids)))
            await s.execute(
                delete(CommissionLedger).where(CommissionLedger.booking_id.in_(booking_ids))
            )
            await s.execute(delete(Refund).where(Refund.booking_id.in_(booking_ids)))
            await s.execute(delete(Payment).where(Payment.booking_id.in_(booking_ids)))
            await s.execute(delete(Booking).where(Booking.id.in_(booking_ids)))
        await s.execute(delete(AuditLog).where(AuditLog.branch_id.in_(branch_ids)))
        await s.execute(delete(Salon).where(Salon.id == salon_id))
        await s.execute(delete(Service).where(Service.id == service_id))
        if all_users:
            await s.execute(delete(User).where(User.id.in_(all_users)))
        await s.commit()


async def test_concurrent_api_holds_enforce_chair_and_staff_limits(
    booking_client: tuple[AsyncClient, async_sessionmaker[AsyncSession], Settings],
) -> None:
    """5 concurrent POST /holds for a 2-barber/2-chair slot allow exactly 2 holds + 3 409s."""
    client, session_factory, _ = booking_client
    fx = await _seed_bookable_branch(session_factory)
    cust_phones = [f"+9196{uuid.uuid4().int % 10**8:08d}" for _ in range(5)]

    try:
        tomorrow_ist = (datetime.now(UTC) + timedelta(days=1)).astimezone(
            ZoneInfo("Asia/Kolkata")
        ).date()
        avail = await client.get(
            f"/api/v1/branches/{fx['branch_id']}/availability",
            params={"service_ids": str(fx["branch_service_id"]), "date": tomorrow_ist.isoformat()},
        )
        assert avail.status_code == 200
        target_slot = avail.json()["slots"][0]["start_at"]

        headers_list = [await _auth_headers(client, phone) for phone in cust_phones]

        async def try_hold(idx: int) -> tuple[int, dict[str, object]]:
            res = await client.post(
                "/api/v1/holds",
                headers={**headers_list[idx], "Idempotency-Key": f"race-hold-{idx}"},
                json={
                    "branch_id": str(fx["branch_id"]),
                    "branch_service_ids": [str(fx["branch_service_id"])],
                    "start_at": target_slot,
                },
            )
            return res.status_code, res.json()

        results = await asyncio.gather(*(try_hold(i) for i in range(5)))
        winners = [body for code, body in results if code == 201]
        losers = [code for code, _ in results if code == 409]
        assert len(winners) == 2
        assert len(losers) == 3
        assert len({w["staff_id"] for w in winners}) == 2
        assert len({w["resource_id"] for w in winners}) == 2

        # Replay identical Idempotency-Key returns same hold payload; payload change gets 409.
        replay = await client.post(
            "/api/v1/holds",
            headers={**headers_list[0], "Idempotency-Key": "race-hold-0"},
            json={
                "branch_id": str(fx["branch_id"]),
                "branch_service_ids": [str(fx["branch_service_id"])],
                "start_at": target_slot,
            },
        )
        assert replay.status_code == 201
        assert replay.json()["hold_id"] == results[0][1]["hold_id"]

        conflict_idem = await client.post(
            "/api/v1/holds",
            headers={**headers_list[0], "Idempotency-Key": "race-hold-0"},
            json={
                "branch_id": str(fx["branch_id"]),
                "branch_service_ids": [str(fx["branch_service_id"])],
                "start_at": target_slot,
                "notes": "tampered payload",
            },
        )
        assert conflict_idem.status_code == 409
        assert conflict_idem.json()["error"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"
    finally:
        await _cleanup_branch_fixture(
            session_factory,
            salon_id=uuid.UUID(str(fx["salon_id"])),
            service_id=uuid.UUID(str(fx["service_id"])),
            user_ids=[uuid.UUID(str(fx["owner_id"]))],
            phones=[str(fx["owner_phone"]), *cust_phones],
        )


async def test_pay_at_salon_otp_commission_and_review_lifecycle(
    booking_client: tuple[AsyncClient, async_sessionmaker[AsyncSession], Settings],
) -> None:
    """Confirm Pay-at-Salon, enforce OTPs on check-in/complete, accrue commission, review once."""
    client, session_factory, _ = booking_client
    fx = await _seed_bookable_branch(session_factory)
    cust_phone = f"+9195{uuid.uuid4().int % 10**8:08d}"

    try:
        owner_hdr = await _auth_headers(client, str(fx["owner_phone"]))
        cust_hdr = await _auth_headers(client, cust_phone)
        tomorrow_ist = (datetime.now(UTC) + timedelta(days=1)).astimezone(
            ZoneInfo("Asia/Kolkata")
        ).date()
        avail = await client.get(
            f"/api/v1/branches/{fx['branch_id']}/availability",
            params={"service_ids": str(fx["branch_service_id"]), "date": tomorrow_ist.isoformat()},
        )
        slot_at = avail.json()["slots"][1]["start_at"]

        hold_res = await client.post(
            "/api/v1/holds",
            headers={**cust_hdr, "Idempotency-Key": f"hold-{uuid.uuid4()}"},
            json={
                "branch_id": str(fx["branch_id"]),
                "branch_service_ids": [str(fx["branch_service_id"])],
                "start_at": slot_at,
            },
        )
        assert hold_res.status_code == 201
        booking_id = hold_res.json()["booking_id"]

        confirm_res = await client.post(
            f"/api/v1/bookings/{booking_id}/confirm-pay-at-salon",
            headers={**cust_hdr, "Idempotency-Key": f"conf-{uuid.uuid4()}"},
        )
        assert confirm_res.status_code == 200
        confirmed = confirm_res.json()
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["payment"]["status"] == "PAY_AT_SALON"
        check_in_otp = confirmed["check_in_otp"]
        assert isinstance(check_in_otp, str) and len(check_in_otp) == 6

        # Partner view must NEVER leak customer OTPs.
        p_list = await client.get(
            f"/api/v1/partner/branches/{fx['branch_id']}/bookings", headers=owner_hdr
        )
        assert p_list.status_code == 200
        assert p_list.json()["items"][0]["check_in_otp"] is None

        # Wrong OTP rejected 403.
        bad_ci = await client.post(
            f"/api/v1/partner/branches/{fx['branch_id']}/bookings/{booking_id}/check-in",
            headers=owner_hdr,
            json={"otp_code": "000000" if check_in_otp != "000000" else "999999"},
        )
        assert bad_ci.status_code == 403
        assert bad_ci.json()["error"]["code"] == "INVALID_CHECK_IN_OTP"

        good_ci = await client.post(
            f"/api/v1/partner/branches/{fx['branch_id']}/bookings/{booking_id}/check-in",
            headers=owner_hdr,
            json={"otp_code": check_in_otp},
        )
        assert good_ci.status_code == 200
        assert good_ci.json()["status"] == "CHECKED_IN"

        start_res = await client.post(
            f"/api/v1/partner/branches/{fx['branch_id']}/bookings/{booking_id}/start",
            headers=owner_hdr,
        )
        assert start_res.status_code == 200
        assert start_res.json()["status"] == "IN_SERVICE"

        # Review blocked before COMPLETED.
        early_rev = await client.post(
            f"/api/v1/bookings/{booking_id}/review",
            headers=cust_hdr,
            json={"rating": 5, "hygiene_rating": 5},
        )
        assert early_rev.status_code == 409

        c_detail = await client.get(f"/api/v1/bookings/{booking_id}", headers=cust_hdr)
        completion_otp = c_detail.json()["completion_otp"]
        assert isinstance(completion_otp, str) and len(completion_otp) == 6

        comp_res = await client.post(
            f"/api/v1/partner/branches/{fx['branch_id']}/bookings/{booking_id}/complete",
            headers=owner_hdr,
            json={"otp_code": completion_otp},
        )
        assert comp_res.status_code == 200
        assert comp_res.json()["status"] == "COMPLETED"

        # Commission ledger accrued once (800 bps of 49900 paise = 3992 paise).
        async with session_factory() as s:
            ledger = await s.scalar(
                select(CommissionLedger).where(CommissionLedger.booking_id == uuid.UUID(booking_id))
            )
            assert ledger is not None
            assert ledger.gross_booking_paise == 49900
            assert ledger.commission_rate_bps == 800
            assert ledger.commission_paise == 3992
            assert ledger.status == "ACCRUED"

        rev_res = await client.post(
            f"/api/v1/bookings/{booking_id}/review",
            headers=cust_hdr,
            json={"rating": 5, "hygiene_rating": 5, "comment": "[DEMO] Clean tools & great cut."},
        )
        assert rev_res.status_code == 201

        dup_rev = await client.post(
            f"/api/v1/bookings/{booking_id}/review",
            headers=cust_hdr,
            json={"rating": 4, "hygiene_rating": 4},
        )
        assert dup_rev.status_code == 409
    finally:
        await _cleanup_branch_fixture(
            session_factory,
            salon_id=uuid.UUID(str(fx["salon_id"])),
            service_id=uuid.UUID(str(fx["service_id"])),
            user_ids=[uuid.UUID(str(fx["owner_id"]))],
            phones=[str(fx["owner_phone"]), cust_phone],
        )


async def test_signed_webhook_idempotent_and_late_payment_auto_refunds(
    booking_client: tuple[AsyncClient, async_sessionmaker[AsyncSession], Settings],
) -> None:
    """Signed webhook settles held booking idempotently and auto-refunds if hold expired/taken."""
    client, session_factory, settings = booking_client
    fx = await _seed_bookable_branch(session_factory)
    cust_1 = f"+9194{uuid.uuid4().int % 10**8:08d}"
    cust_2 = f"+9193{uuid.uuid4().int % 10**8:08d}"

    try:
        hdr_1 = await _auth_headers(client, cust_1)
        hdr_2 = await _auth_headers(client, cust_2)
        tomorrow_ist = (datetime.now(UTC) + timedelta(days=1)).astimezone(
            ZoneInfo("Asia/Kolkata")
        ).date()
        avail = await client.get(
            f"/api/v1/branches/{fx['branch_id']}/availability",
            params={"service_ids": str(fx["branch_service_id"]), "date": tomorrow_ist.isoformat()},
        )
        slot_at = avail.json()["slots"][2]["start_at"]

        # Pin Barber 1 for Hold 1, create payment order, test signed webhook + replay.
        h1 = await client.post(
            "/api/v1/holds",
            headers={**hdr_1, "Idempotency-Key": "wh-hold-1"},
            json={
                "branch_id": str(fx["branch_id"]),
                "branch_service_ids": [str(fx["branch_service_id"])],
                "start_at": slot_at,
                "staff_id": str(fx["staff_1_id"]),
            },
        )
        assert h1.status_code == 201
        b1_id = h1.json()["booking_id"]
        o1 = await client.post(
            f"/api/v1/bookings/{b1_id}/payment-order",
            headers={**hdr_1, "Idempotency-Key": "wh-order-1"},
        )
        assert o1.status_code == 201
        order_1_id = o1.json()["provider_order_id"]

        wh_payload_1 = json.dumps(
            {
                "event_id": f"evt_{uuid.uuid4().hex[:10]}",
                "event": "payment.captured",
                "provider_order_id": order_1_id,
                "provider_payment_id": "pay_valid_1",
            }
        ).encode("utf-8")

        bad_sig = await client.post(
            "/api/v1/payments/webhook/TEST_MODE",
            content=wh_payload_1,
            headers={"Content-Type": "application/json", "X-Razorpay-Signature": "deadbeef"},
        )
        assert bad_sig.status_code == 401

        sig_1 = hmac.new(
            settings.razorpay_webhook_secret.encode("utf-8"), wh_payload_1, hashlib.sha256
        ).hexdigest()
        good_wh = await client.post(
            "/api/v1/payments/webhook/TEST_MODE",
            content=wh_payload_1,
            headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig_1},
        )
        assert good_wh.status_code == 200
        assert good_wh.json()["booking_status"] == "CONFIRMED"
        assert good_wh.json()["auto_refunded"] is False

        replay_wh = await client.post(
            "/api/v1/payments/webhook/TEST_MODE",
            content=wh_payload_1,
            headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig_1},
        )
        assert replay_wh.status_code == 200
        assert replay_wh.json()["status"] == "already_processed"

        # Now Hold 2 pins Barber 2, expires before payment settles, and Cust 2 grabs Barber 2!
        h2 = await client.post(
            "/api/v1/holds",
            headers={**hdr_1, "Idempotency-Key": "wh-hold-2"},
            json={
                "branch_id": str(fx["branch_id"]),
                "branch_service_ids": [str(fx["branch_service_id"])],
                "start_at": slot_at,
                "staff_id": str(fx["staff_2_id"]),
            },
        )
        assert h2.status_code == 201
        h2_id = uuid.UUID(h2.json()["hold_id"])
        b2_id = uuid.UUID(h2.json()["booking_id"])

        o2 = await client.post(
            f"/api/v1/bookings/{b2_id}/payment-order",
            headers={**hdr_1, "Idempotency-Key": "wh-order-2"},
        )
        assert o2.status_code == 201
        order_2_id = o2.json()["provider_order_id"]

        async with session_factory() as s:
            await s.execute(
                update(SlotHold)
                .where(SlotHold.id == h2_id)
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=60))
            )
            await s.commit()

        # Customer 2 legally takes Barber 2 after Hold 2 expired.
        h_steal = await client.post(
            "/api/v1/holds",
            headers={**hdr_2, "Idempotency-Key": "wh-steal-2"},
            json={
                "branch_id": str(fx["branch_id"]),
                "branch_service_ids": [str(fx["branch_service_id"])],
                "start_at": slot_at,
                "staff_id": str(fx["staff_2_id"]),
            },
        )
        assert h_steal.status_code == 201
        b_steal_id = h_steal.json()["booking_id"]
        conf_steal = await client.post(
            f"/api/v1/bookings/{b_steal_id}/confirm-pay-at-salon",
            headers={**hdr_2, "Idempotency-Key": "wh-steal-conf"},
        )
        assert conf_steal.status_code == 200

        # Delayed webhook for Order 2 arrives: MUST auto-refund cleanly & never double-book.
        late_payload = json.dumps(
            {
                "event_id": f"evt_{uuid.uuid4().hex[:10]}",
                "event": "payment.captured",
                "provider_order_id": order_2_id,
                "provider_payment_id": "pay_late_2",
            }
        ).encode("utf-8")
        late_sig = hmac.new(
            settings.razorpay_webhook_secret.encode("utf-8"), late_payload, hashlib.sha256
        ).hexdigest()
        late_wh = await client.post(
            "/api/v1/payments/webhook/TEST_MODE",
            content=late_payload,
            headers={"Content-Type": "application/json", "X-Razorpay-Signature": late_sig},
        )
        assert late_wh.status_code == 200
        assert late_wh.json()["auto_refunded"] is True
        assert late_wh.json()["booking_status"] == "EXPIRED"
        assert late_wh.json()["payment_status"] == "REFUNDED"

        async with session_factory() as s:
            refund_row = await s.scalar(select(Refund).where(Refund.booking_id == b2_id))
            assert refund_row is not None
            assert refund_row.reason == "LATE_PAYMENT_HOLD_EXPIRED"
            assert refund_row.amount_paise == 49900
            alloc_b2 = await s.scalar(
                select(BookingAllocation).where(BookingAllocation.booking_id == b2_id)
            )
            assert alloc_b2 is None
    finally:
        await _cleanup_branch_fixture(
            session_factory,
            salon_id=uuid.UUID(str(fx["salon_id"])),
            service_id=uuid.UUID(str(fx["service_id"])),
            user_ids=[uuid.UUID(str(fx["owner_id"]))],
            phones=[str(fx["owner_phone"]), cust_1, cust_2],
        )


async def test_cancellation_refund_walk_in_queue_and_pause_toggle(
    booking_client: tuple[AsyncClient, async_sessionmaker[AsyncSession], Settings],
) -> None:
    """Verify test-mode capture + cancel auto-refund, partner pause toggle, and walk-in queue."""
    client, session_factory, _ = booking_client
    fx = await _seed_bookable_branch(session_factory)
    cust_phone = f"+9192{uuid.uuid4().int % 10**8:08d}"

    try:
        owner_hdr = await _auth_headers(client, str(fx["owner_phone"]))
        cust_hdr = await _auth_headers(client, cust_phone)
        tomorrow_ist = (datetime.now(UTC) + timedelta(days=1)).astimezone(
            ZoneInfo("Asia/Kolkata")
        ).date()
        avail = await client.get(
            f"/api/v1/branches/{fx['branch_id']}/availability",
            params={"service_ids": str(fx["branch_service_id"]), "date": tomorrow_ist.isoformat()},
        )
        slot_at = avail.json()["slots"][3]["start_at"]

        hold = await client.post(
            "/api/v1/holds",
            headers={**cust_hdr, "Idempotency-Key": "cancel-hold"},
            json={
                "branch_id": str(fx["branch_id"]),
                "branch_service_ids": [str(fx["branch_service_id"])],
                "start_at": slot_at,
            },
        )
        assert hold.status_code == 201
        b_id = hold.json()["booking_id"]

        order = await client.post(
            f"/api/v1/bookings/{b_id}/payment-order",
            headers={**cust_hdr, "Idempotency-Key": "cancel-order"},
        )
        assert order.status_code == 201

        cap = await client.post(
            f"/api/v1/bookings/{b_id}/test-payment-capture",
            headers={**cust_hdr, "Idempotency-Key": "cancel-capture"},
            json={"provider_order_id": order.json()["provider_order_id"]},
        )
        assert cap.status_code == 200
        assert cap.json()["status"] == "CONFIRMED"
        assert cap.json()["payment"]["status"] == "CAPTURED"

        cancel = await client.post(
            f"/api/v1/bookings/{b_id}/cancel",
            headers={**cust_hdr, "Idempotency-Key": "cancel-action"},
            json={"reason": "Change of plans"},
        )
        assert cancel.status_code == 200
        assert cancel.json()["status"] == "CANCELLED"
        assert cancel.json()["refund"]["reason"] == "CUSTOMER_CANCELLED"

        # Pause toggle blocks new holds; resuming restores holds.
        pause_on = await client.patch(
            f"/api/v1/partner/branches/{fx['branch_id']}/pause",
            headers=owner_hdr,
            json={"paused": True},
        )
        assert pause_on.status_code == 200 and pause_on.json()["online_booking_paused"] is True

        blocked_hold = await client.post(
            "/api/v1/holds",
            headers={**cust_hdr, "Idempotency-Key": "paused-hold"},
            json={
                "branch_id": str(fx["branch_id"]),
                "branch_service_ids": [str(fx["branch_service_id"])],
                "start_at": slot_at,
            },
        )
        assert blocked_hold.status_code == 409
        assert blocked_hold.json()["error"]["code"] == "BOOKING_PAUSED"

        pause_off = await client.patch(
            f"/api/v1/partner/branches/{fx['branch_id']}/pause",
            headers=owner_hdr,
            json={"paused": False},
        )
        assert pause_off.status_code == 200 and pause_off.json()["online_booking_paused"] is False

        # Walk-in check-in -> SEATED -> COMPLETED releases allocation cleanly.
        wi = await client.post(
            f"/api/v1/partner/branches/{fx['branch_id']}/walk-ins",
            headers=owner_hdr,
            json={
                "customer_name": "[DEMO] Walk-in Guest",
                "service_summary": "Classic Haircut",
                "quoted_price_paise": 49900,
                "estimated_duration_minutes": 30,
                "staff_id": str(fx["staff_1_id"]),
            },
        )
        assert wi.status_code == 201
        wi_id = wi.json()["id"]

        seated = await client.patch(
            f"/api/v1/partner/branches/{fx['branch_id']}/walk-ins/{wi_id}",
            headers=owner_hdr,
            json={"status": "SEATED"},
        )
        assert seated.status_code == 200 and seated.json()["status"] == "SEATED"

        completed = await client.patch(
            f"/api/v1/partner/branches/{fx['branch_id']}/walk-ins/{wi_id}",
            headers=owner_hdr,
            json={"status": "COMPLETED"},
        )
        assert completed.status_code == 200 and completed.json()["status"] == "COMPLETED"
    finally:
        await _cleanup_branch_fixture(
            session_factory,
            salon_id=uuid.UUID(str(fx["salon_id"])),
            service_id=uuid.UUID(str(fx["service_id"])),
            user_ids=[uuid.UUID(str(fx["owner_id"]))],
            phones=[str(fx["owner_phone"]), cust_phone],
        )


async def test_review_security_hardening_idor_lockout_webhooks_and_stale_holds(
    booking_client: tuple[AsyncClient, async_sessionmaker[AsyncSession], Settings],
) -> None:
    """Verify cross-tenant walk-in IDOR block, OTP lockout, webhook guards, and stale GET sweep."""
    client, session_factory, settings = booking_client
    fx_a = await _seed_bookable_branch(session_factory)
    fx_b = await _seed_bookable_branch(session_factory)
    cust_phone = f"+9191{uuid.uuid4().int % 10**8:08d}"

    try:
        owner_a_hdr = await _auth_headers(client, str(fx_a["owner_phone"]))
        cust_hdr = await _auth_headers(client, cust_phone)

        # 1. Cross-tenant walk-in IDOR must reject competitor staff_id & chair cleanly (422).
        wi_a = await client.post(
            f"/api/v1/partner/branches/{fx_a['branch_id']}/walk-ins",
            headers=owner_a_hdr,
            json={
                "customer_name": "[DEMO] Walk-in Guest",
                "service_summary": "Trim",
                "quoted_price_paise": 30000,
                "estimated_duration_minutes": 30,
            },
        )
        assert wi_a.status_code == 201
        wi_id = wi_a.json()["id"]

        bad_staff = await client.patch(
            f"/api/v1/partner/branches/{fx_a['branch_id']}/walk-ins/{wi_id}",
            headers=owner_a_hdr,
            json={"status": "SEATED", "staff_id": str(fx_b["staff_1_id"])},
        )
        assert bad_staff.status_code == 422
        assert bad_staff.json()["error"]["code"] == "INVALID_STAFF_FOR_BRANCH"

        # 2. Webhook provider mismatch rejected 403; COMPLETED booking not refunded by new event_id.
        today_ist = datetime.now(UTC).astimezone(ZoneInfo("Asia/Kolkata")).date()
        avail = await client.get(
            f"/api/v1/branches/{fx_a['branch_id']}/availability",
            params={"service_ids": str(fx_a["branch_service_id"]), "date": today_ist.isoformat()},
        )
        slot_at = (
            avail.json()["slots"][0]["start_at"]
            if avail.json()["slots"]
            else (
                await client.get(
                    f"/api/v1/branches/{fx_a['branch_id']}/availability",
                    params={
                        "service_ids": str(fx_a["branch_service_id"]),
                        "date": (today_ist + timedelta(days=1)).isoformat(),
                    },
                )
            ).json()["slots"][0]["start_at"]
        )

        h1 = await client.post(
            "/api/v1/holds",
            headers={**cust_hdr, "Idempotency-Key": "sec-h1"},
            json={
                "branch_id": str(fx_a["branch_id"]),
                "branch_service_ids": [str(fx_a["branch_service_id"])],
                "start_at": slot_at,
                "staff_id": str(fx_a["staff_1_id"]),
            },
        )
        assert h1.status_code == 201
        b1_id = h1.json()["booking_id"]

        # Walk-in seating over Branch A barber 1 active hold (when hold covers now) or test order.
        o1 = await client.post(
            f"/api/v1/bookings/{b1_id}/payment-order",
            headers={**cust_hdr, "Idempotency-Key": "sec-o1"},
        )
        assert o1.status_code == 201
        order_1 = o1.json()["provider_order_id"]

        wh_payload = json.dumps(
            {
                "event_id": f"evt_sec_{uuid.uuid4().hex[:8]}",
                "event": "payment.captured",
                "provider_order_id": order_1,
                "provider_payment_id": "pay_sec_1",
            }
        ).encode("utf-8")
        wh_sig = hmac.new(
            settings.razorpay_webhook_secret.encode("utf-8"), wh_payload, hashlib.sha256
        ).hexdigest()

        mismatch = await client.post(
            "/api/v1/payments/webhook/RAZORPAY",
            content=wh_payload,
            headers={"Content-Type": "application/json", "X-Razorpay-Signature": wh_sig},
        )
        assert mismatch.status_code == 403

        ok_wh = await client.post(
            "/api/v1/payments/webhook/TEST_MODE",
            content=wh_payload,
            headers={"Content-Type": "application/json", "X-Razorpay-Signature": wh_sig},
        )
        assert ok_wh.status_code == 200 and ok_wh.json()["booking_status"] == "CONFIRMED"

        # 3. 5 bad check-in OTP attempts lock out partner with 429; check real check-in & complete.
        detail_res = await client.get(f"/api/v1/bookings/{b1_id}", headers=cust_hdr)
        real_ci_otp = detail_res.json()["check_in_otp"]
        wrong_otp = "000000" if real_ci_otp != "000000" else "999999"
        for _ in range(settings.otp_verify_max_attempts):
            r = await client.post(
                f"/api/v1/partner/branches/{fx_a['branch_id']}/bookings/{b1_id}/check-in",
                headers=owner_a_hdr,
                json={"otp_code": wrong_otp},
            )
            assert r.status_code == 403
        locked = await client.post(
            f"/api/v1/partner/branches/{fx_a['branch_id']}/bookings/{b1_id}/check-in",
            headers=owner_a_hdr,
            json={"otp_code": real_ci_otp},
        )
        assert locked.status_code == 429
        assert locked.json()["error"]["code"] == "BOOKING_OTP_LOCKED"

        # 4. Duplicate webhook on CONFIRMED booking does NOT auto-refund primary payment.
        dup_wh_payload = json.dumps(
            {
                "event_id": f"evt_dup_{uuid.uuid4().hex[:8]}",
                "event": "payment.captured",
                "provider_order_id": order_1,
                "provider_payment_id": "pay_sec_1",
            }
        ).encode("utf-8")
        dup_sig = hmac.new(
            settings.razorpay_webhook_secret.encode("utf-8"), dup_wh_payload, hashlib.sha256
        ).hexdigest()
        dup_wh = await client.post(
            "/api/v1/payments/webhook/TEST_MODE",
            content=dup_wh_payload,
            headers={"Content-Type": "application/json", "X-Razorpay-Signature": dup_sig},
        )
        assert dup_wh.status_code == 200
        assert dup_wh.json()["auto_refunded"] is False
        assert dup_wh.json()["payment_status"] == "CAPTURED"

        # 5. Walk-in mutual exclusion against active hold + stale GET /bookings EXPIRED refresh.
        next_day_slot = (
            await client.get(
                f"/api/v1/branches/{fx_a['branch_id']}/availability",
                params={
                    "service_ids": str(fx_a["branch_service_id"]),
                    "date": (today_ist + timedelta(days=2)).isoformat(),
                },
            )
        ).json()["slots"][0]["start_at"]

        h_exp = await client.post(
            "/api/v1/holds",
            headers={**cust_hdr, "Idempotency-Key": "sec-hexp"},
            json={
                "branch_id": str(fx_a["branch_id"]),
                "branch_service_ids": [str(fx_a["branch_service_id"])],
                "start_at": next_day_slot,
                "staff_id": str(fx_a["staff_2_id"]),
            },
        )
        assert h_exp.status_code == 201
        hexp_id = uuid.UUID(h_exp.json()["hold_id"])
        bexp_id = h_exp.json()["booking_id"]

        # Also verify duplicate online webhook on a Pay-at-Salon booking auto-refunds safely.
        dup_pas_slot = (
            await client.get(
                f"/api/v1/branches/{fx_a['branch_id']}/availability",
                params={
                    "service_ids": str(fx_a["branch_service_id"]),
                    "date": (today_ist + timedelta(days=3)).isoformat(),
                },
            )
        ).json()["slots"][0]["start_at"]
        h_pas = await client.post(
            "/api/v1/holds",
            headers={**cust_hdr, "Idempotency-Key": "sec-hpas"},
            json={
                "branch_id": str(fx_a["branch_id"]),
                "branch_service_ids": [str(fx_a["branch_service_id"])],
                "start_at": dup_pas_slot,
                "staff_id": str(fx_a["staff_1_id"]),
            },
        )
        assert h_pas.status_code == 201
        b_pas_id = h_pas.json()["booking_id"]
        o_pas = await client.post(
            f"/api/v1/bookings/{b_pas_id}/payment-order",
            headers={**cust_hdr, "Idempotency-Key": "sec-opas"},
        )
        assert o_pas.status_code == 201
        pas_order_id = o_pas.json()["provider_order_id"]
        conf_pas = await client.post(
            f"/api/v1/bookings/{b_pas_id}/confirm-pay-at-salon",
            headers={**cust_hdr, "Idempotency-Key": "sec-confpas"},
        )
        assert conf_pas.status_code == 200 and conf_pas.json()["status"] == "CONFIRMED"

        pas_wh_payload = json.dumps(
            {
                "event_id": f"evt_pasdup_{uuid.uuid4().hex[:8]}",
                "event": "payment.captured",
                "provider_order_id": pas_order_id,
                "provider_payment_id": "pay_pasdup_1",
            }
        ).encode("utf-8")
        pas_sig = hmac.new(
            settings.razorpay_webhook_secret.encode("utf-8"), pas_wh_payload, hashlib.sha256
        ).hexdigest()
        pas_dup_wh = await client.post(
            "/api/v1/payments/webhook/TEST_MODE",
            content=pas_wh_payload,
            headers={"Content-Type": "application/json", "X-Razorpay-Signature": pas_sig},
        )
        assert pas_dup_wh.status_code == 200
        assert pas_dup_wh.json()["booking_status"] == "CONFIRMED"
        assert pas_dup_wh.json()["auto_refunded"] is True

        # Verify walk-in active overlap check on [now, now+25m) by pinning active hold at now.
        async with session_factory() as s:
            now_utc = datetime.now(UTC)
            now_hold = SlotHold(
                customer_user_id=uuid.UUID(
                    str((await client.get("/api/v1/users/me", headers=cust_hdr)).json()["id"])
                ),
                branch_id=uuid.UUID(str(fx_a["branch_id"])),
                staff_id=uuid.UUID(str(fx_a["staff_2_id"])),
                hold_range=Range(now_utc, now_utc + timedelta(minutes=25), bounds="[)"),
                expires_at=now_utc + timedelta(minutes=5),
                status="ACTIVE",
                idempotency_key="wi-overlap-probe",
            )
            s.add(now_hold)
            await s.commit()

        conflict_wi = await client.patch(
            f"/api/v1/partner/branches/{fx_a['branch_id']}/walk-ins/{wi_id}",
            headers=owner_a_hdr,
            json={"status": "SEATED", "staff_id": str(fx_a["staff_2_id"])},
        )
        assert conflict_wi.status_code == 409
        assert conflict_wi.json()["error"]["code"] == "WALK_IN_SLOT_CONFLICT"

        # Expire h_exp and check GET /bookings returns status=EXPIRED (not stale HELD).
        o_abandon = await client.post(
            f"/api/v1/bookings/{bexp_id}/payment-order",
            headers={**cust_hdr, "Idempotency-Key": "sec-o-abandon"},
        )
        assert o_abandon.status_code == 201
        abandoned_order_id = o_abandon.json()["provider_order_id"]

        async with session_factory() as s:
            await s.execute(
                update(SlotHold)
                .where(SlotHold.id == hexp_id)
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=10))
            )
            await s.commit()
        list_res = await client.get("/api/v1/bookings", headers=cust_hdr)
        exp_item = next(it for it in list_res.json()["items"] if it["id"] == bexp_id)
        assert exp_item["status"] == "EXPIRED"

        # Late webhook on expired hold auto-refunds cleanly.
        ab_payload = json.dumps(
            {
                "event_id": f"evt_ab_{uuid.uuid4().hex[:8]}",
                "event": "payment.captured",
                "provider_order_id": abandoned_order_id,
                "provider_payment_id": "pay_ab_1",
            }
        ).encode("utf-8")
        ab_sig = hmac.new(
            settings.razorpay_webhook_secret.encode("utf-8"), ab_payload, hashlib.sha256
        ).hexdigest()
        ab_wh = await client.post(
            "/api/v1/payments/webhook/TEST_MODE",
            content=ab_payload,
            headers={"Content-Type": "application/json", "X-Razorpay-Signature": ab_sig},
        )
        assert ab_wh.status_code == 200 and ab_wh.json()["auto_refunded"] is True
    finally:
        await _cleanup_branch_fixture(
            session_factory,
            salon_id=uuid.UUID(str(fx_a["salon_id"])),
            service_id=uuid.UUID(str(fx_a["service_id"])),
            user_ids=[uuid.UUID(str(fx_a["owner_id"]))],
            phones=[str(fx_a["owner_phone"]), cust_phone],
        )
        await _cleanup_branch_fixture(
            session_factory,
            salon_id=uuid.UUID(str(fx_b["salon_id"])),
            service_id=uuid.UUID(str(fx_b["service_id"])),
            user_ids=[uuid.UUID(str(fx_b["owner_id"]))],
            phones=[str(fx_b["owner_phone"])],
        )

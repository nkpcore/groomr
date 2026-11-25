"""Authoritative booking engine: 5-min holds, allocations, OTPs, payments, refunds, walk-ins."""

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import status
from sqlalchemy import and_, desc, select, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from chair_api.adapters.base import PaymentProvider
from chair_api.core.auth_store import AuthStore
from chair_api.core.config import Settings
from chair_api.core.errors import ChairAPIError
from chair_api.db.models import (
    Booking,
    BookingAllocation,
    BookingItem,
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
    Subscription,
    SubscriptionPlan,
    WalkIn,
)
from chair_api.domain.booking_states import validate_booking_transition
from chair_api.domain.enums import (
    BookingStatus,
    BranchVerificationStatus,
    PaymentProviderName,
    PaymentStatus,
    RefundReason,
    RefundStatus,
    SlotHoldStatus,
    UserRole,
    WalkInStatus,
)
from chair_api.security.rbac import AuthPrincipal
from chair_api.services.audit import record_audit_log
from chair_api.services.availability import (
    DEFAULT_TIMEZONE,
    load_branch_availability_from_db,
)
from chair_api.services.idempotency import (
    acquire_idempotency_replay,
    compute_request_hash,
    record_idempotency_response,
    require_idempotency_key,
)


def _generate_booking_code(now_utc: datetime) -> str:
    return f"CHR-{now_utc.strftime('%y%m')}-{uuid.uuid4().hex[:6].upper()}"


def generate_booking_otp(
    settings: Settings,
    booking_id: uuid.UUID,
    booking_code: str,
    purpose: Literal["check_in", "completion"],
) -> str:
    """Derive a booking-unique 6-digit OTP bound to app secret key."""
    digest = hmac.new(
        settings.secret_key.encode("utf-8"),
        f"chair-otp:{purpose}:{booking_id}:{booking_code}".encode(),
        hashlib.sha256,
    ).digest()
    numeric = int.from_bytes(digest[:4], "big") % 900_000 + 100_000
    return f"{numeric:06d}"


def hash_booking_otp(
    settings: Settings,
    booking_id: uuid.UUID,
    purpose: Literal["check_in", "completion"],
    otp_code: str,
) -> str:
    """Hash a booking OTP for one-way storage in PostgreSQL."""
    return hashlib.sha256(
        f"{booking_id}:{purpose}:{otp_code.strip()}:{settings.secret_key}".encode()
    ).hexdigest()


def verify_booking_otp(
    settings: Settings,
    booking_id: uuid.UUID,
    purpose: Literal["check_in", "completion"],
    provided_otp: str,
    stored_hash: str | None,
) -> bool:
    """Verify a customer-presented OTP constant-time against stored SHA-256 digest."""
    if not stored_hash:
        return False
    expected = hash_booking_otp(settings, booking_id, purpose, provided_otp)
    return hmac.compare_digest(expected, stored_hash)


def resolve_webhook_hmac_key(settings: Settings) -> str:
    """Return configured webhook signing key or dev/test deterministic key."""
    if settings.razorpay_webhook_secret:
        return settings.razorpay_webhook_secret
    if settings.payment_provider == "test_mode" and settings.app_env in ("development", "test"):
        return hmac.new(
            settings.secret_key.encode("utf-8"),
            b"chair-test-mode-webhook-key",
            hashlib.sha256,
        ).hexdigest()
    raise ChairAPIError(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        code="WEBHOOK_KEY_UNCONFIGURED",
        message="Payment webhook signing key is not configured.",
    )


async def expire_stale_holds(
    session: AsyncSession,
    *,
    branch_id: uuid.UUID | None = None,
    hold_ids: list[uuid.UUID] | None = None,
    now_utc: datetime | None = None,
) -> list[uuid.UUID]:
    """Expire overdue ACTIVE holds and linked HELD bookings in canonical lock order."""
    current_utc = now_utc or datetime.now(UTC)
    conditions = [
        SlotHold.status == SlotHoldStatus.ACTIVE.value,
        SlotHold.expires_at <= current_utc,
    ]
    if branch_id is not None:
        conditions.append(SlotHold.branch_id == branch_id)
    if hold_ids:
        conditions.append(SlotHold.id.in_(hold_ids))

    overdue_holds = list(
        await session.scalars(
            select(SlotHold)
            .where(and_(*conditions))
            .order_by(SlotHold.id.asc())
            .with_for_update(skip_locked=True)
        )
    )
    if not overdue_holds:
        return []

    expired_ids = [h.id for h in overdue_holds]
    for hold in overdue_holds:
        hold.status = SlotHoldStatus.EXPIRED.value
        hold.updated_at = current_utc

    held_bookings = list(
        await session.scalars(
            select(Booking)
            .where(
                Booking.slot_hold_id.in_(expired_ids),
                Booking.status == BookingStatus.HELD.value,
            )
            .order_by(Booking.id.asc())
            .with_for_update()
        )
    )
    for booking in held_bookings:
        booking.status = BookingStatus.EXPIRED.value
        booking.updated_at = current_utc

    await session.flush()
    return expired_ids


async def _lock_booking_graph(
    session: AsyncSession,
    *,
    booking_id: uuid.UUID | None = None,
    hold_id: uuid.UUID | None = None,
    order_id: str | None = None,
    order_provider: str | None = None,
) -> tuple[SlotHold | None, Booking | None, list[Payment]]:
    """Lock hold -> booking -> payments in strict global canonical order (deadlock-free)."""
    resolved_booking_id = booking_id
    resolved_hold_id = hold_id

    if resolved_booking_id is None and order_id is not None:
        p_stmt = select(Payment.booking_id).where(Payment.provider_order_id == order_id)
        if order_provider is not None:
            p_stmt = p_stmt.where(Payment.provider == order_provider)
        resolved_booking_id = await session.scalar(p_stmt)

    if resolved_booking_id is None and resolved_hold_id is not None:
        resolved_booking_id = await session.scalar(
            select(Booking.id)
            .where(Booking.slot_hold_id == resolved_hold_id)
            .order_by(Booking.id.asc())
        )

    if resolved_hold_id is None and resolved_booking_id is not None:
        resolved_hold_id = await session.scalar(
            select(Booking.slot_hold_id).where(Booking.id == resolved_booking_id)
        )

    hold: SlotHold | None = None
    if resolved_hold_id is not None:
        hold = await session.scalar(
            select(SlotHold)
            .where(SlotHold.id == resolved_hold_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )

    booking: Booking | None = None
    if resolved_booking_id is not None:
        booking = await session.scalar(
            select(Booking)
            .where(Booking.id == resolved_booking_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )

    payments: list[Payment] = []
    if booking is not None:
        payments = list(
            await session.scalars(
                select(Payment)
                .where(Payment.booking_id == booking.id)
                .order_by(Payment.id.asc())
                .execution_options(populate_existing=True)
                .with_for_update()
            )
        )

    return hold, booking, payments


async def _has_overlapping_capacity_demand(
    session: AsyncSession,
    *,
    branch_id: uuid.UUID,
    staff_id: uuid.UUID,
    resource_id: uuid.UUID | None,
    interval_range: Range[datetime],
    now_utc: datetime,
    exclude_walk_in_id: uuid.UUID | None = None,
) -> bool:
    """Lock Staff -> Resource and verify neither BookingAllocation nor SlotHold overlaps."""
    await session.scalar(select(Staff.id).where(Staff.id == staff_id).with_for_update())
    if resource_id is not None:
        await session.scalar(
            select(Resource.id).where(Resource.id == resource_id).with_for_update()
        )

    alloc_staff_cond = [
        BookingAllocation.staff_id == staff_id,
        BookingAllocation.is_active.is_(True),
        BookingAllocation.allocated_range.op("&&")(interval_range),
    ]
    if exclude_walk_in_id is not None:
        alloc_staff_cond.append(
            (BookingAllocation.walk_in_id.is_(None))
            | (BookingAllocation.walk_in_id != exclude_walk_in_id)
        )
    if (
        await session.scalar(select(BookingAllocation.id).where(and_(*alloc_staff_cond)))
        is not None
    ):
        return True

    hold_staff_overlap = await session.scalar(
        select(SlotHold.id).where(
            SlotHold.branch_id == branch_id,
            SlotHold.staff_id == staff_id,
            SlotHold.status == SlotHoldStatus.ACTIVE.value,
            SlotHold.expires_at > now_utc,
            SlotHold.hold_range.op("&&")(interval_range),
        )
    )
    if hold_staff_overlap is not None:
        return True

    if resource_id is not None:
        alloc_res_cond = [
            BookingAllocation.resource_id == resource_id,
            BookingAllocation.is_active.is_(True),
            BookingAllocation.allocated_range.op("&&")(interval_range),
        ]
        if exclude_walk_in_id is not None:
            alloc_res_cond.append(
                (BookingAllocation.walk_in_id.is_(None))
                | (BookingAllocation.walk_in_id != exclude_walk_in_id)
            )
        if (
            await session.scalar(select(BookingAllocation.id).where(and_(*alloc_res_cond)))
            is not None
        ):
            return True

        hold_res_overlap = await session.scalar(
            select(SlotHold.id).where(
                SlotHold.branch_id == branch_id,
                SlotHold.resource_id == resource_id,
                SlotHold.status == SlotHoldStatus.ACTIVE.value,
                SlotHold.expires_at > now_utc,
                SlotHold.hold_range.op("&&")(interval_range),
            )
        )
        if hold_res_overlap is not None:
            return True

    return False


@dataclass(frozen=True, slots=True)
class HoldCreationPayload:
    hold_id: uuid.UUID
    booking_id: uuid.UUID
    booking_code: str
    status: str
    hold_status: str
    expires_at: datetime
    hold_ttl_seconds: int
    branch_id: uuid.UUID
    branch_name: str
    staff_id: uuid.UUID
    staff_name: str
    resource_id: uuid.UUID | None
    resource_name: str | None
    scheduled_start_at: datetime
    scheduled_end_at: datetime
    total_price_paise: int
    discount_paise: int
    net_payable_paise: int
    items: list[dict[str, Any]]


def _hold_to_dict(data: HoldCreationPayload) -> dict[str, Any]:
    return {
        "hold_id": str(data.hold_id),
        "booking_id": str(data.booking_id),
        "booking_code": data.booking_code,
        "status": data.status,
        "hold_status": data.hold_status,
        "expires_at": data.expires_at.isoformat(),
        "hold_ttl_seconds": data.hold_ttl_seconds,
        "branch_id": str(data.branch_id),
        "branch_name": data.branch_name,
        "staff_id": str(data.staff_id),
        "staff_name": data.staff_name,
        "resource_id": str(data.resource_id) if data.resource_id else None,
        "resource_name": data.resource_name,
        "scheduled_start_at": data.scheduled_start_at.isoformat(),
        "scheduled_end_at": data.scheduled_end_at.isoformat(),
        "total_price_paise": data.total_price_paise,
        "discount_paise": data.discount_paise,
        "net_payable_paise": data.net_payable_paise,
        "items": data.items,
    }


async def _find_free_chairs(
    session: AsyncSession,
    *,
    branch_id: uuid.UUID,
    alloc_start: datetime,
    alloc_end: datetime,
    now_utc: datetime,
) -> list[Resource]:
    chairs = list(
        await session.scalars(
            select(Resource)
            .where(Resource.branch_id == branch_id, Resource.is_active.is_(True))
            .order_by(Resource.created_at.asc(), Resource.id.asc())
        )
    )
    if not chairs:
        return []

    query_range = Range(alloc_start, alloc_end, bounds="[)")
    busy_alloc_rows = list(
        await session.scalars(
            select(BookingAllocation.resource_id).where(
                BookingAllocation.branch_id == branch_id,
                BookingAllocation.is_active.is_(True),
                BookingAllocation.resource_id.is_not(None),
                BookingAllocation.allocated_range.op("&&")(query_range),
            )
        )
    )
    busy_hold_rows = list(
        await session.scalars(
            select(SlotHold.resource_id).where(
                SlotHold.branch_id == branch_id,
                SlotHold.status == SlotHoldStatus.ACTIVE.value,
                SlotHold.expires_at > now_utc,
                SlotHold.resource_id.is_not(None),
                SlotHold.hold_range.op("&&")(query_range),
            )
        )
    )
    busy_ids = {rid for rid in busy_alloc_rows if rid is not None} | {
        rid for rid in busy_hold_rows if rid is not None
    }
    return [chair for chair in chairs if chair.id not in busy_ids]


async def create_slot_hold_and_booking(
    session: AsyncSession,
    *,
    principal: AuthPrincipal,
    settings: Settings,
    idempotency_key_raw: str | None,
    branch_id: uuid.UUID,
    branch_service_ids: list[uuid.UUID],
    start_at: datetime,
    staff_id: uuid.UUID | None,
    notes: str | None,
) -> tuple[int, dict[str, Any]]:
    """Atomically lock a 5-minute SlotHold + HELD Booking with btree_gist protection."""
    idem_key = require_idempotency_key(idempotency_key_raw)
    unique_service_ids = list(dict.fromkeys(branch_service_ids))
    start_utc = start_at.astimezone(UTC) if start_at.tzinfo else start_at.replace(tzinfo=UTC)
    req_hash = compute_request_hash(
        {
            "branch_id": str(branch_id),
            "branch_service_ids": [str(sid) for sid in unique_service_ids],
            "start_at": start_utc.isoformat(),
            "staff_id": str(staff_id) if staff_id else None,
            "notes": (notes or "").strip(),
        }
    )

    endpoint = f"POST:/holds:{branch_id}"
    actor_key = f"user:{principal.user.id}"
    replay = await acquire_idempotency_replay(
        session,
        actor_key=actor_key,
        endpoint=endpoint,
        idempotency_key=idem_key,
        request_hash=req_hash,
    )
    if replay is not None:
        return replay.status_code, replay.body

    now_utc = datetime.now(UTC)
    await expire_stale_holds(session, branch_id=branch_id, now_utc=now_utc)

    target_date_local = start_utc.astimezone(ZoneInfo(DEFAULT_TIMEZONE)).date()
    branch, avail = await load_branch_availability_from_db(
        session,
        branch_id=branch_id,
        service_ids=unique_service_ids,
        target_date=target_date_local,
        staff_id=staff_id,
        now_utc=now_utc,
    )
    if branch.online_booking_paused:
        raise ChairAPIError(
            status_code=status.HTTP_409_CONFLICT,
            code="BOOKING_PAUSED",
            message="Online bookings are temporarily paused at this branch.",
        )

    matched_slot = next((sl for sl in avail.slots if sl.start_at == start_utc), None)
    if matched_slot is None or not matched_slot.available_staff:
        raise ChairAPIError(
            status_code=status.HTTP_409_CONFLICT,
            code="SLOT_NOT_AVAILABLE",
            message="The requested time slot is no longer available.",
        )

    svc_rows = list(
        (
            await session.execute(
                select(BranchService, Service)
                .join(Service, Service.id == BranchService.service_id)
                .where(
                    BranchService.branch_id == branch.id,
                    BranchService.is_active.is_(True),
                    Service.is_active.is_(True),
                    BranchService.id.in_(unique_service_ids),
                )
            )
        ).all()
    )
    svc_map = {bs.id: (bs, svc) for bs, svc in svc_rows}
    ordered_svcs = [svc_map[sid] for sid in unique_service_ids]

    buf_before = ordered_svcs[0][0].buffer_before_minutes
    buf_after = ordered_svcs[-1][0].buffer_after_minutes
    total_price_paise = sum(bs.price_paise for bs, _ in ordered_svcs)
    expires_at = now_utc + timedelta(seconds=settings.booking_hold_ttl_seconds)

    acquired_hold: SlotHold | None = None
    chosen_staff = None
    chosen_chair: Resource | None = None
    chosen_end = matched_slot.end_at

    for staff_opt in matched_slot.available_staff:
        service_end = staff_opt.end_at
        alloc_start = start_utc - timedelta(minutes=buf_before)
        alloc_end = service_end + timedelta(minutes=buf_after)
        hold_range = Range(alloc_start, alloc_end, bounds="[)")

        free_chairs = await _find_free_chairs(
            session,
            branch_id=branch.id,
            alloc_start=alloc_start,
            alloc_end=alloc_end,
            now_utc=now_utc,
        )
        for chair in free_chairs:
            try:
                async with session.begin_nested():
                    busy = await _has_overlapping_capacity_demand(
                        session,
                        branch_id=branch.id,
                        staff_id=staff_opt.staff_id,
                        resource_id=chair.id,
                        interval_range=hold_range,
                        now_utc=now_utc,
                    )
                    if busy:
                        continue
                    hold = SlotHold(
                        customer_user_id=principal.user.id,
                        branch_id=branch.id,
                        staff_id=staff_opt.staff_id,
                        resource_id=chair.id,
                        hold_range=hold_range,
                        expires_at=expires_at,
                        status=SlotHoldStatus.ACTIVE.value,
                        idempotency_key=idem_key,
                    )
                    session.add(hold)
                    await session.flush()
                    acquired_hold = hold
                    chosen_staff = staff_opt
                    chosen_chair = chair
                    chosen_end = service_end
                    break
            except IntegrityError:
                continue
        if acquired_hold is not None:
            break

    if acquired_hold is None or chosen_staff is None or chosen_chair is None:
        raise ChairAPIError(
            status_code=status.HTTP_409_CONFLICT,
            code="SLOT_NO_LONGER_AVAILABLE",
            message="This slot was just reserved by another guest. Pick another time.",
        )

    staff_durations_rows = list(
        await session.scalars(
            select(StaffService).where(
                StaffService.staff_id == chosen_staff.staff_id,
                StaffService.branch_service_id.in_(unique_service_ids),
                StaffService.is_active.is_(True),
            )
        )
    )
    custom_dur_by_bs = {
        row.branch_service_id: row.custom_duration_minutes
        for row in staff_durations_rows
        if row.custom_duration_minutes is not None
    }

    booking = Booking(
        booking_code=_generate_booking_code(now_utc),
        customer_user_id=principal.user.id,
        branch_id=branch.id,
        slot_hold_id=acquired_hold.id,
        source="PLATFORM",
        booking_mode="INSTANT",
        status=BookingStatus.HELD.value,
        scheduled_start_at=start_utc,
        scheduled_end_at=chosen_end,
        total_price_paise=total_price_paise,
        discount_paise=0,
        net_payable_paise=total_price_paise,
        is_featured_attribution=branch.is_featured,
        notes=(notes or "").strip() or None,
    )
    session.add(booking)
    await session.flush()

    item_dtos: list[dict[str, Any]] = []
    for order_idx, (bs, svc) in enumerate(ordered_svcs):
        dur_snapshot = custom_dur_by_bs.get(bs.id, bs.duration_minutes)
        b_item = BookingItem(
            booking_id=booking.id,
            branch_service_id=bs.id,
            service_name_snapshot=bs.display_name_en,
            category_snapshot=svc.category,
            unit_price_paise_snapshot=bs.price_paise,
            duration_minutes_snapshot=dur_snapshot,
            buffer_before_minutes_snapshot=bs.buffer_before_minutes,
            buffer_after_minutes_snapshot=bs.buffer_after_minutes,
            sort_order=order_idx,
        )
        session.add(b_item)
        item_dtos.append(
            {
                "branch_service_id": str(bs.id),
                "service_name_en": bs.display_name_en,
                "service_name_hi": bs.display_name_hi,
                "category": svc.category,
                "unit_price_paise": bs.price_paise,
                "duration_minutes": dur_snapshot,
            }
        )

    await record_audit_log(
        session,
        actor_user_id=principal.user.id,
        actor_role=principal.primary_role,
        action="HOLD_CREATED",
        resource_type="slot_hold",
        resource_id=str(acquired_hold.id),
        branch_id=branch.id,
        after_state={
            "booking_id": str(booking.id),
            "staff_id": str(chosen_staff.staff_id),
            "resource_id": str(chosen_chair.id),
            "expires_at": expires_at.isoformat(),
        },
        request_id=principal.request_id,
        ip_address=principal.ip_address,
    )

    body = _hold_to_dict(
        HoldCreationPayload(
            hold_id=acquired_hold.id,
            booking_id=booking.id,
            booking_code=booking.booking_code,
            status=booking.status,
            hold_status=acquired_hold.status,
            expires_at=expires_at,
            hold_ttl_seconds=settings.booking_hold_ttl_seconds,
            branch_id=branch.id,
            branch_name=branch.name,
            staff_id=chosen_staff.staff_id,
            staff_name=chosen_staff.display_name,
            resource_id=chosen_chair.id,
            resource_name=chosen_chair.name,
            scheduled_start_at=start_utc,
            scheduled_end_at=chosen_end,
            total_price_paise=total_price_paise,
            discount_paise=0,
            net_payable_paise=total_price_paise,
            items=item_dtos,
        )
    )
    await record_idempotency_response(
        session,
        actor_key=actor_key,
        endpoint=endpoint,
        idempotency_key=idem_key,
        request_hash=req_hash,
        response_status=status.HTTP_201_CREATED,
        response_body=body,
        now_utc=now_utc,
    )
    await session.commit()
    return status.HTTP_201_CREATED, body


async def serialize_booking_detail(
    session: AsyncSession,
    *,
    booking: Booking,
    settings: Settings,
    include_customer_otps: bool,
) -> dict[str, Any]:
    """Serialize authoritative Booking detail including snapshot items, payment, refund, review."""
    branch = await session.scalar(select(Branch).where(Branch.id == booking.branch_id))
    hold = (
        await session.scalar(select(SlotHold).where(SlotHold.id == booking.slot_hold_id))
        if booking.slot_hold_id is not None
        else None
    )
    alloc = await session.scalar(
        select(BookingAllocation)
        .where(BookingAllocation.booking_id == booking.id)
        .order_by(desc(BookingAllocation.is_active), desc(BookingAllocation.created_at))
    )
    staff_id = alloc.staff_id if alloc else (hold.staff_id if hold else None)
    resource_id = alloc.resource_id if alloc else (hold.resource_id if hold else None)

    staff_obj = (
        await session.scalar(select(Staff).where(Staff.id == staff_id)) if staff_id else None
    )
    chair_obj = (
        await session.scalar(select(Resource).where(Resource.id == resource_id))
        if resource_id
        else None
    )
    items = list(
        await session.scalars(
            select(BookingItem)
            .where(BookingItem.booking_id == booking.id)
            .order_by(BookingItem.sort_order.asc())
        )
    )
    latest_payment = await session.scalar(
        select(Payment)
        .where(Payment.booking_id == booking.id)
        .order_by(desc(Payment.created_at))
    )
    latest_refund = await session.scalar(
        select(Refund)
        .where(Refund.booking_id == booking.id)
        .order_by(desc(Refund.created_at))
    )
    review_obj = await session.scalar(select(Review).where(Review.booking_id == booking.id))

    check_in_otp: str | None = None
    completion_otp: str | None = None
    if include_customer_otps:
        if booking.status == BookingStatus.CONFIRMED.value and booking.check_in_otp_hash:
            candidate = generate_booking_otp(
                settings, booking.id, booking.booking_code, "check_in"
            )
            if verify_booking_otp(
                settings, booking.id, "check_in", candidate, booking.check_in_otp_hash
            ):
                check_in_otp = candidate
        if (
            booking.status in (BookingStatus.CHECKED_IN.value, BookingStatus.IN_SERVICE.value)
            and booking.completion_otp_hash
        ):
            candidate = generate_booking_otp(
                settings, booking.id, booking.booking_code, "completion"
            )
            if verify_booking_otp(
                settings, booking.id, "completion", candidate, booking.completion_otp_hash
            ):
                completion_otp = candidate

    return {
        "id": str(booking.id),
        "booking_code": booking.booking_code,
        "status": booking.status,
        "source": booking.source,
        "booking_mode": booking.booking_mode,
        "branch_id": str(booking.branch_id),
        "branch_name": branch.name if branch else "",
        "branch_city": branch.city if branch else "",
        "slot_hold_id": str(booking.slot_hold_id) if booking.slot_hold_id else None,
        "hold_expires_at": hold.expires_at.isoformat() if hold else None,
        "hold_status": hold.status if hold else None,
        "staff_id": str(staff_obj.id) if staff_obj else None,
        "staff_name": staff_obj.display_name if staff_obj else None,
        "resource_id": str(chair_obj.id) if chair_obj else None,
        "resource_name": chair_obj.name if chair_obj else None,
        "scheduled_start_at": booking.scheduled_start_at.isoformat(),
        "scheduled_end_at": booking.scheduled_end_at.isoformat(),
        "total_price_paise": booking.total_price_paise,
        "discount_paise": booking.discount_paise,
        "net_payable_paise": booking.net_payable_paise,
        "notes": booking.notes,
        "check_in_otp": check_in_otp,
        "completion_otp": completion_otp,
        "checked_in_at": booking.checked_in_at.isoformat() if booking.checked_in_at else None,
        "started_at": booking.started_at.isoformat() if booking.started_at else None,
        "completed_at": booking.completed_at.isoformat() if booking.completed_at else None,
        "cancelled_at": booking.cancelled_at.isoformat() if booking.cancelled_at else None,
        "cancellation_reason": booking.cancellation_reason,
        "items": [
            {
                "id": str(it.id),
                "branch_service_id": str(it.branch_service_id) if it.branch_service_id else None,
                "service_name_snapshot": it.service_name_snapshot,
                "category_snapshot": it.category_snapshot,
                "unit_price_paise_snapshot": it.unit_price_paise_snapshot,
                "duration_minutes_snapshot": it.duration_minutes_snapshot,
            }
            for it in items
        ],
        "payment": (
            {
                "id": str(latest_payment.id),
                "provider": latest_payment.provider,
                "provider_order_id": latest_payment.provider_order_id,
                "provider_payment_id": latest_payment.provider_payment_id,
                "amount_paise": latest_payment.amount_paise,
                "currency": latest_payment.currency,
                "status": latest_payment.status,
                "paid_at": latest_payment.paid_at.isoformat() if latest_payment.paid_at else None,
            }
            if latest_payment
            else None
        ),
        "refund": (
            {
                "id": str(latest_refund.id),
                "amount_paise": latest_refund.amount_paise,
                "reason": latest_refund.reason,
                "status": latest_refund.status,
                "provider_refund_id": latest_refund.provider_refund_id,
            }
            if latest_refund
            else None
        ),
        "has_review": review_obj is not None,
    }


def _assign_booking_otps(booking: Booking, settings: Settings) -> None:
    c_otp = generate_booking_otp(settings, booking.id, booking.booking_code, "check_in")
    f_otp = generate_booking_otp(settings, booking.id, booking.booking_code, "completion")
    booking.check_in_otp_hash = hash_booking_otp(settings, booking.id, "check_in", c_otp)
    booking.completion_otp_hash = hash_booking_otp(settings, booking.id, "completion", f_otp)


async def confirm_booking_pay_at_salon(
    session: AsyncSession,
    *,
    principal: AuthPrincipal,
    settings: Settings,
    booking_id: uuid.UUID,
    idempotency_key_raw: str | None,
) -> tuple[int, dict[str, Any]]:
    """Convert an active HELD booking into CONFIRMED with Pay-at-Salon settlement."""
    idem_key = require_idempotency_key(idempotency_key_raw)
    endpoint = f"POST:/bookings/{booking_id}/confirm-pay-at-salon"
    actor_key = f"user:{principal.user.id}"
    req_hash = compute_request_hash({"booking_id": str(booking_id), "mode": "PAY_AT_SALON"})

    replay = await acquire_idempotency_replay(
        session,
        actor_key=actor_key,
        endpoint=endpoint,
        idempotency_key=idem_key,
        request_hash=req_hash,
    )
    if replay is not None:
        return replay.status_code, replay.body

    now_utc = datetime.now(UTC)
    hold, booking, _ = await _lock_booking_graph(session, booking_id=booking_id)
    if booking is None or (
        booking.customer_user_id != principal.user.id
        and UserRole.ADMIN not in principal.role_set
    ):
        raise ChairAPIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="BOOKING_NOT_FOUND",
            message="Booking was not found.",
        )

    actor_role = (
        UserRole.CUSTOMER
        if principal.user.id == booking.customer_user_id
        else UserRole.ADMIN
    )
    validate_booking_transition(
        current_status=BookingStatus(booking.status),
        target_status=BookingStatus.CONFIRMED,
        actor_role=actor_role,
    )

    if hold is None or hold.status != SlotHoldStatus.ACTIVE.value or hold.expires_at <= now_utc:
        if hold is not None and hold.status == SlotHoldStatus.ACTIVE.value:
            hold.status = SlotHoldStatus.EXPIRED.value
        if booking.status == BookingStatus.HELD.value:
            booking.status = BookingStatus.EXPIRED.value
        await session.commit()
        raise ChairAPIError(
            status_code=status.HTTP_409_CONFLICT,
            code="HOLD_EXPIRED",
            message="Your 5-minute slot hold expired. Please select a time again.",
        )

    branch = await session.scalar(
        select(Branch)
        .join(Salon, Salon.id == Branch.salon_id)
        .where(
            Branch.id == booking.branch_id,
            Branch.status == "ACTIVE",
            Salon.status == "ACTIVE",
            Branch.verification_status != BranchVerificationStatus.SUSPENDED.value,
        )
    )
    if branch is None or branch.online_booking_paused:
        raise ChairAPIError(
            status_code=status.HTTP_409_CONFLICT,
            code="BOOKING_PAUSED",
            message="Online bookings are unavailable at this branch right now.",
        )

    hold.status = SlotHoldStatus.CONVERTED.value
    try:
        async with session.begin_nested():
            session.add(
                BookingAllocation(
                    booking_id=booking.id,
                    branch_id=hold.branch_id,
                    staff_id=hold.staff_id,
                    resource_id=hold.resource_id,
                    allocated_range=hold.hold_range,
                    is_active=True,
                )
            )
            await session.flush()
    except IntegrityError as exc:
        raise ChairAPIError(
            status_code=status.HTTP_409_CONFLICT,
            code="SLOT_CONFLICT",
            message="This chair or barber is already allocated for the selected time.",
        ) from exc

    booking.status = BookingStatus.CONFIRMED.value
    _assign_booking_otps(booking, settings)

    session.add(
        Payment(
            booking_id=booking.id,
            provider=PaymentProviderName.PAY_AT_SALON.value,
            amount_paise=booking.net_payable_paise,
            currency="INR",
            status=PaymentStatus.PAY_AT_SALON.value,
        )
    )
    await record_audit_log(
        session,
        actor_user_id=principal.user.id,
        actor_role=principal.primary_role,
        action="BOOKING_CONFIRMED_PAY_AT_SALON",
        resource_type="booking",
        resource_id=str(booking.id),
        branch_id=booking.branch_id,
        after_state={"booking_code": booking.booking_code, "status": booking.status},
        request_id=principal.request_id,
        ip_address=principal.ip_address,
    )

    body = await serialize_booking_detail(
        session, booking=booking, settings=settings, include_customer_otps=True
    )
    await record_idempotency_response(
        session,
        actor_key=actor_key,
        endpoint=endpoint,
        idempotency_key=idem_key,
        request_hash=req_hash,
        response_status=status.HTTP_200_OK,
        response_body=body,
        now_utc=now_utc,
    )
    await session.commit()
    return status.HTTP_200_OK, body


async def create_booking_payment_order(
    session: AsyncSession,
    *,
    principal: AuthPrincipal,
    payment_provider: PaymentProvider,
    booking_id: uuid.UUID,
    idempotency_key_raw: str | None,
) -> tuple[int, dict[str, Any]]:
    """Create a payment gateway order (TEST_MODE or Razorpay) for an active HELD booking."""
    idem_key = require_idempotency_key(idempotency_key_raw)
    endpoint = f"POST:/bookings/{booking_id}/payment-order"
    actor_key = f"user:{principal.user.id}"
    req_hash = compute_request_hash({"booking_id": str(booking_id)})

    replay = await acquire_idempotency_replay(
        session,
        actor_key=actor_key,
        endpoint=endpoint,
        idempotency_key=idem_key,
        request_hash=req_hash,
    )
    if replay is not None:
        return replay.status_code, replay.body

    now_utc = datetime.now(UTC)
    hold, booking, existing_payments = await _lock_booking_graph(
        session, booking_id=booking_id
    )
    if booking is None or booking.customer_user_id != principal.user.id:
        raise ChairAPIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="BOOKING_NOT_FOUND",
            message="Booking was not found.",
        )

    if booking.net_payable_paise <= 0:
        raise ChairAPIError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="ZERO_AMOUNT_USE_PAY_AT_SALON",
            message="Zero-rupee bookings must be confirmed via Pay at Salon.",
        )

    if (
        booking.status != BookingStatus.HELD.value
        or hold is None
        or hold.status != SlotHoldStatus.ACTIVE.value
        or hold.expires_at <= now_utc
    ):
        if (
            hold is not None
            and hold.status == SlotHoldStatus.ACTIVE.value
            and hold.expires_at <= now_utc
        ):
            hold.status = SlotHoldStatus.EXPIRED.value
        if booking.status == BookingStatus.HELD.value:
            booking.status = BookingStatus.EXPIRED.value
        await session.commit()
        raise ChairAPIError(
            status_code=status.HTTP_409_CONFLICT,
            code="HOLD_EXPIRED",
            message="This slot hold is no longer active.",
        )

    for stale_pay in existing_payments:
        if stale_pay.status == PaymentStatus.PENDING.value:
            stale_pay.status = PaymentStatus.FAILED.value

    order = await payment_provider.create_order(
        booking_id=str(booking.id),
        amount_paise=booking.net_payable_paise,
        currency="INR",
    )
    payment = Payment(
        booking_id=booking.id,
        provider=order.provider,
        provider_order_id=order.provider_order_id,
        amount_paise=order.amount_paise,
        currency=order.currency,
        status=PaymentStatus.PENDING.value,
    )
    session.add(payment)
    await session.flush()

    body = {
        "payment_id": str(payment.id),
        "booking_id": str(booking.id),
        "provider": payment.provider,
        "provider_order_id": payment.provider_order_id,
        "amount_paise": payment.amount_paise,
        "currency": payment.currency,
        "status": payment.status,
    }
    await record_idempotency_response(
        session,
        actor_key=actor_key,
        endpoint=endpoint,
        idempotency_key=idem_key,
        request_hash=req_hash,
        response_status=status.HTTP_201_CREATED,
        response_body=body,
        now_utc=now_utc,
    )
    await session.commit()
    return status.HTTP_201_CREATED, body


async def _issue_auto_refund_once(
    session: AsyncSession,
    *,
    payment: Payment,
    booking: Booking,
    reason: str,
    audit_action: str,
    now_utc: datetime,
    actor_user_id: uuid.UUID | None,
    actor_role: str,
    request_id: str | None = None,
    ip_address: str | None = None,
) -> None:
    """Create at most one PROCESSED Refund for payment and mark payment REFUNDED."""
    payment.status = PaymentStatus.REFUNDED.value
    payment.paid_at = payment.paid_at or now_utc
    existing_refund = await session.scalar(select(Refund).where(Refund.payment_id == payment.id))
    if existing_refund is None and payment.amount_paise > 0:
        session.add(
            Refund(
                payment_id=payment.id,
                booking_id=booking.id,
                amount_paise=payment.amount_paise,
                reason=reason,
                provider_refund_id=f"rfnd_{uuid.uuid4().hex[:14]}",
                status=RefundStatus.PROCESSED.value,
                initiated_by=actor_user_id,
                processed_at=now_utc,
            )
        )
    await record_audit_log(
        session,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=audit_action,
        resource_type="refund",
        resource_id=str(payment.id),
        branch_id=booking.branch_id,
        after_state={
            "booking_id": str(booking.id),
            "booking_status": booking.status,
            "reason": reason,
        },
        request_id=request_id,
        ip_address=ip_address,
    )


async def _settle_captured_payment(
    session: AsyncSession,
    *,
    payment: Payment,
    hold: SlotHold | None,
    booking: Booking,
    all_payments: list[Payment],
    provider_payment_id: str,
    settings: Settings,
    now_utc: datetime,
    actor_user_id: uuid.UUID | None,
    actor_role: str,
    request_id: str | None = None,
    ip_address: str | None = None,
) -> tuple[Booking, bool]:
    """Confirm held booking on captured payment or auto-refund on expired/duplicate slots."""
    if payment.status in (PaymentStatus.CAPTURED.value, PaymentStatus.REFUNDED.value):
        return booking, False

    payment.provider_payment_id = provider_payment_id

    if booking.status in (
        BookingStatus.CONFIRMED.value,
        BookingStatus.CHECKED_IN.value,
        BookingStatus.IN_SERVICE.value,
        BookingStatus.COMPLETED.value,
    ):
        other_settled = any(
            p.id != payment.id
            and p.status
            in (PaymentStatus.CAPTURED.value, PaymentStatus.PAY_AT_SALON.value)
            for p in all_payments
        )
        if not other_settled:
            payment.status = PaymentStatus.CAPTURED.value
            payment.paid_at = payment.paid_at or now_utc
            return booking, False
        await _issue_auto_refund_once(
            session,
            payment=payment,
            booking=booking,
            reason=RefundReason.DISPUTE_RESOLUTION.value,
            audit_action="DUPLICATE_PAYMENT_AUTO_REFUNDED",
            now_utc=now_utc,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            request_id=request_id,
            ip_address=ip_address,
        )
        return booking, True

    if booking.status == BookingStatus.CANCELLED.value:
        await _issue_auto_refund_once(
            session,
            payment=payment,
            booking=booking,
            reason=RefundReason.CUSTOMER_CANCELLED.value,
            audit_action="CANCELLED_BOOKING_PAYMENT_REFUNDED",
            now_utc=now_utc,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            request_id=request_id,
            ip_address=ip_address,
        )
        return booking, True

    branch = await session.scalar(
        select(Branch)
        .join(Salon, Salon.id == Branch.salon_id)
        .where(
            Branch.id == booking.branch_id,
            Branch.status == "ACTIVE",
            Salon.status == "ACTIVE",
            Branch.verification_status != BranchVerificationStatus.SUSPENDED.value,
        )
    )

    hold_active_and_fresh = (
        hold is not None
        and hold.status == SlotHoldStatus.ACTIVE.value
        and hold.expires_at > now_utc
        and booking.status == BookingStatus.HELD.value
        and branch is not None
        and not branch.online_booking_paused
    )

    if hold_active_and_fresh and hold is not None:
        try:
            async with session.begin_nested():
                hold.status = SlotHoldStatus.CONVERTED.value
                session.add(
                    BookingAllocation(
                        booking_id=booking.id,
                        branch_id=hold.branch_id,
                        staff_id=hold.staff_id,
                        resource_id=hold.resource_id,
                        allocated_range=hold.hold_range,
                        is_active=True,
                    )
                )
                await session.flush()
            validate_booking_transition(
                current_status=BookingStatus.HELD,
                target_status=BookingStatus.CONFIRMED,
                actor_role="SYSTEM",
            )
            booking.status = BookingStatus.CONFIRMED.value
            _assign_booking_otps(booking, settings)
            payment.status = PaymentStatus.CAPTURED.value
            payment.paid_at = now_utc
            await record_audit_log(
                session,
                actor_user_id=actor_user_id,
                actor_role=actor_role,
                action="BOOKING_CONFIRMED_ONLINE_PAYMENT",
                resource_type="booking",
                resource_id=str(booking.id),
                branch_id=booking.branch_id,
                after_state={
                    "payment_id": str(payment.id),
                    "provider_payment_id": provider_payment_id,
                },
                request_id=request_id,
                ip_address=ip_address,
            )
            return booking, False
        except IntegrityError:
            pass

    if hold is not None and hold.status == SlotHoldStatus.ACTIVE.value:
        hold.status = SlotHoldStatus.EXPIRED.value
    if booking.status == BookingStatus.HELD.value:
        booking.status = BookingStatus.EXPIRED.value

    await _issue_auto_refund_once(
        session,
        payment=payment,
        booking=booking,
        reason=RefundReason.LATE_PAYMENT_HOLD_EXPIRED.value,
        audit_action="LATE_PAYMENT_AUTO_REFUNDED",
        now_utc=now_utc,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        request_id=request_id,
        ip_address=ip_address,
    )
    return booking, True


async def handle_payment_webhook(
    session: AsyncSession,
    *,
    provider: str,
    raw_body: bytes,
    signature: str,
    payment_provider: PaymentProvider,
    settings: Settings,
) -> dict[str, Any]:
    """Verify signed webhook bytes and idempotently process captured payment or auto-refund."""
    normalized_provider = provider.upper()
    if normalized_provider not in (
        PaymentProviderName.TEST_MODE.value,
        PaymentProviderName.RAZORPAY.value,
    ):
        raise ChairAPIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="UNKNOWN_PAYMENT_PROVIDER",
            message="Unsupported payment webhook provider.",
        )

    expected_provider = settings.payment_provider.upper()
    if normalized_provider != expected_provider:
        raise ChairAPIError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="WEBHOOK_PROVIDER_MISMATCH",
            message="Webhook provider does not match active payment configuration.",
        )
    if normalized_provider == PaymentProviderName.TEST_MODE.value and (
        settings.app_env in ("staging", "production") or not settings.payment_test_mode
    ):
        raise ChairAPIError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="TEST_PAYMENT_DISABLED",
            message="Test-mode webhooks are disabled in staging and production.",
        )

    webhook_key = resolve_webhook_hmac_key(settings)
    if not payment_provider.verify_webhook_signature(
        payload_bytes=raw_body, signature=signature, secret=webhook_key
    ):
        raise ChairAPIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_WEBHOOK_SIGNATURE",
            message="Webhook HMAC signature verification failed.",
        )

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except ValueError as exc:
        raise ChairAPIError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="INVALID_WEBHOOK_JSON",
            message="Webhook payload must be valid JSON.",
        ) from exc

    event_id = str(payload.get("event_id") or "").strip()
    event_type = str(payload.get("event") or "").strip()
    order_id = str(payload.get("provider_order_id") or payload.get("order_id") or "").strip()
    payment_ref = str(payload.get("provider_payment_id") or payload.get("payment_id") or "").strip()
    if not event_id or not event_type or not order_id:
        raise ChairAPIError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="INVALID_WEBHOOK_PAYLOAD",
            message="Webhook requires event_id, event, and provider_order_id.",
        )

    now_utc = datetime.now(UTC)
    existing_evt = await session.scalar(
        select(PaymentEvent).where(
            PaymentEvent.provider == normalized_provider,
            PaymentEvent.provider_event_id == event_id,
        )
    )
    if existing_evt is not None:
        return {"status": "already_processed", "event_id": event_id}

    hold, booking, locked_payments = await _lock_booking_graph(
        session, order_id=order_id, order_provider=normalized_provider
    )
    payment = next(
        (
            p
            for p in locked_payments
            if p.provider_order_id == order_id and p.provider == normalized_provider
        ),
        None,
    )
    if payment is None or booking is None:
        raise ChairAPIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="PAYMENT_ORDER_NOT_FOUND",
            message="Payment order referenced by webhook does not exist.",
        )

    evt = PaymentEvent(
        payment_id=payment.id,
        provider=normalized_provider,
        provider_event_id=event_id,
        event_type=event_type,
        signature_verified=True,
        payload_json=payload,
        processed_at=now_utc,
    )
    session.add(evt)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return {"status": "already_processed", "event_id": event_id}

    auto_refunded = False
    booking_status = booking.status
    if event_type == "payment.captured":
        settled_booking, auto_refunded = await _settle_captured_payment(
            session,
            payment=payment,
            hold=hold,
            booking=booking,
            all_payments=locked_payments,
            provider_payment_id=payment_ref or f"pay_{uuid.uuid4().hex[:12]}",
            settings=settings,
            now_utc=now_utc,
            actor_user_id=None,
            actor_role="SYSTEM",
        )
        booking_status = settled_booking.status
    elif event_type == "payment.failed":
        if payment.status == PaymentStatus.PENDING.value:
            payment.status = PaymentStatus.FAILED.value

    await session.commit()
    return {
        "status": "processed",
        "event_id": event_id,
        "booking_status": booking_status,
        "payment_status": payment.status,
        "auto_refunded": auto_refunded,
    }


async def capture_test_mode_payment(
    session: AsyncSession,
    *,
    principal: AuthPrincipal,
    settings: Settings,
    booking_id: uuid.UUID,
    provider_order_id: str,
    idempotency_key_raw: str | None,
) -> tuple[int, dict[str, Any]]:
    """Simulate Razorpay test-mode client checkout capture cleanly in dev/test only."""
    if (
        settings.app_env not in ("development", "test")
        or settings.payment_provider != "test_mode"
        or not settings.payment_test_mode
    ):
        raise ChairAPIError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="TEST_PAYMENT_DISABLED",
            message="Test payment capture is restricted to development and test environments.",
        )

    idem_key = require_idempotency_key(idempotency_key_raw)
    endpoint = f"POST:/bookings/{booking_id}/test-payment-capture"
    actor_key = f"user:{principal.user.id}"
    req_hash = compute_request_hash(
        {"booking_id": str(booking_id), "provider_order_id": provider_order_id}
    )
    replay = await acquire_idempotency_replay(
        session,
        actor_key=actor_key,
        endpoint=endpoint,
        idempotency_key=idem_key,
        request_hash=req_hash,
    )
    if replay is not None:
        return replay.status_code, replay.body

    now_utc = datetime.now(UTC)
    hold, booking, locked_payments = await _lock_booking_graph(
        session, booking_id=booking_id
    )
    if booking is None or booking.customer_user_id != principal.user.id:
        raise ChairAPIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="BOOKING_NOT_FOUND",
            message="Booking was not found.",
        )

    payment = next(
        (
            p
            for p in locked_payments
            if p.provider_order_id == provider_order_id
            and p.provider == PaymentProviderName.TEST_MODE.value
        ),
        None,
    )
    if payment is None:
        raise ChairAPIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="PAYMENT_ORDER_NOT_FOUND",
            message="Pending test-mode payment order was not found.",
        )

    settled_booking, auto_refunded = await _settle_captured_payment(
        session,
        payment=payment,
        hold=hold,
        booking=booking,
        all_payments=locked_payments,
        provider_payment_id=f"test_pay_{uuid.uuid4().hex[:12]}",
        settings=settings,
        now_utc=now_utc,
        actor_user_id=principal.user.id,
        actor_role=principal.primary_role,
        request_id=principal.request_id,
        ip_address=principal.ip_address,
    )
    if auto_refunded:
        await session.commit()
        raise ChairAPIError(
            status_code=status.HTTP_409_CONFLICT,
            code="HOLD_EXPIRED_AUTO_REFUNDED",
            message="Slot hold expired before payment settled. An automatic refund was processed.",
        )

    body = await serialize_booking_detail(
        session, booking=settled_booking, settings=settings, include_customer_otps=True
    )
    await record_idempotency_response(
        session,
        actor_key=actor_key,
        endpoint=endpoint,
        idempotency_key=idem_key,
        request_hash=req_hash,
        response_status=status.HTTP_200_OK,
        response_body=body,
        now_utc=now_utc,
    )
    await session.commit()
    return status.HTTP_200_OK, body


async def cancel_booking_transaction(
    session: AsyncSession,
    *,
    booking_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_role: UserRole,
    actor_role_label: str,
    reason: str | None,
    idempotency_key_raw: str | None,
    settings: Settings,
    branch_id_scope: uuid.UUID | None = None,
    request_id: str | None = None,
    ip_address: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Cancel a booking, release active holds/allocations, and refund captured payments."""
    idem_key = require_idempotency_key(idempotency_key_raw)
    endpoint = f"POST:/bookings/{booking_id}/cancel:{actor_role_label}"
    actor_key = f"user:{actor_user_id}"
    req_hash = compute_request_hash({"booking_id": str(booking_id), "reason": reason or ""})
    replay = await acquire_idempotency_replay(
        session,
        actor_key=actor_key,
        endpoint=endpoint,
        idempotency_key=idem_key,
        request_hash=req_hash,
    )
    if replay is not None:
        return replay.status_code, replay.body

    now_utc = datetime.now(UTC)
    hold, booking, locked_payments = await _lock_booking_graph(
        session, booking_id=booking_id
    )
    if booking is None or (
        branch_id_scope is not None and booking.branch_id != branch_id_scope
    ) or (actor_role == UserRole.CUSTOMER and booking.customer_user_id != actor_user_id):
        raise ChairAPIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="BOOKING_NOT_FOUND",
            message="Booking was not found.",
        )

    validate_booking_transition(
        current_status=BookingStatus(booking.status),
        target_status=BookingStatus.CANCELLED,
        actor_role=actor_role,
    )

    booking.status = BookingStatus.CANCELLED.value
    booking.cancelled_at = now_utc
    booking.cancelled_by_role = actor_role_label
    booking.cancellation_reason = (reason or "").strip() or None

    if hold is not None and hold.status == SlotHoldStatus.ACTIVE.value:
        hold.status = SlotHoldStatus.RELEASED.value
        hold.updated_at = now_utc

    await session.execute(
        update(BookingAllocation)
        .where(
            BookingAllocation.booking_id == booking.id,
            BookingAllocation.is_active.is_(True),
        )
        .values(is_active=False, updated_at=now_utc)
    )

    refund_reason = (
        RefundReason.CUSTOMER_CANCELLED.value
        if actor_role == UserRole.CUSTOMER
        else RefundReason.PARTNER_CANCELLED.value
    )
    for pay in locked_payments:
        if pay.status == PaymentStatus.CAPTURED.value and pay.amount_paise > 0:
            await _issue_auto_refund_once(
                session,
                payment=pay,
                booking=booking,
                reason=refund_reason,
                audit_action="CANCEL_PAYMENT_REFUNDED",
                now_utc=now_utc,
                actor_user_id=actor_user_id,
                actor_role=actor_role_label,
                request_id=request_id,
                ip_address=ip_address,
            )

    await record_audit_log(
        session,
        actor_user_id=actor_user_id,
        actor_role=actor_role_label,
        action="BOOKING_CANCELLED",
        resource_type="booking",
        resource_id=str(booking.id),
        branch_id=booking.branch_id,
        after_state={"reason": booking.cancellation_reason},
        request_id=request_id,
        ip_address=ip_address,
    )

    body = await serialize_booking_detail(
        session,
        booking=booking,
        settings=settings,
        include_customer_otps=(actor_role == UserRole.CUSTOMER),
    )
    await record_idempotency_response(
        session,
        actor_key=actor_key,
        endpoint=endpoint,
        idempotency_key=idem_key,
        request_hash=req_hash,
        response_status=status.HTTP_200_OK,
        response_body=body,
        now_utc=now_utc,
    )
    await session.commit()
    return status.HTTP_200_OK, body


async def transition_booking_partner(
    session: AsyncSession,
    *,
    branch_id: uuid.UUID,
    booking_id: uuid.UUID,
    target_status: BookingStatus,
    principal: AuthPrincipal,
    settings: Settings,
    otp_code: str | None = None,
    auth_store: AuthStore | None = None,
) -> dict[str, Any]:
    """Advance booking lifecycle on Partner Ops with OTP enforcement and commission accrual."""
    now_utc = datetime.now(UTC)
    booking = await session.scalar(
        select(Booking)
        .where(Booking.id == booking_id, Booking.branch_id == branch_id)
        .with_for_update()
    )
    if booking is None:
        raise ChairAPIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="BOOKING_NOT_FOUND",
            message="Booking was not found for this branch.",
        )

    actor_role = (
        UserRole.ADMIN
        if UserRole.ADMIN in principal.role_set
        else (
            UserRole.PARTNER_OWNER
            if UserRole.PARTNER_OWNER in principal.role_set
            else UserRole.PARTNER_STAFF
        )
    )
    validate_booking_transition(
        current_status=BookingStatus(booking.status),
        target_status=target_status,
        actor_role=actor_role,
    )

    if target_status == BookingStatus.CHECKED_IN:
        if actor_role != UserRole.ADMIN:
            otp_scope = f"{booking.id}:check_in:{principal.user.id}"
            if auth_store is not None:
                locked_for = await auth_store.is_booking_otp_locked(
                    otp_scope, max_failures=settings.otp_verify_max_attempts
                )
                if locked_for is not None:
                    raise ChairAPIError(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        code="BOOKING_OTP_LOCKED",
                        message=f"Too many failed check-in OTP attempts. Retry in {locked_for}s.",
                    )
            if not otp_code or not verify_booking_otp(
                settings, booking.id, "check_in", otp_code, booking.check_in_otp_hash
            ):
                if auth_store is not None:
                    await auth_store.record_booking_otp_failure(
                        otp_scope_key=otp_scope,
                        window_seconds=settings.otp_request_window_seconds,
                        max_failures=settings.otp_verify_max_attempts,
                    )
                raise ChairAPIError(
                    status_code=status.HTTP_403_FORBIDDEN,
                    code="INVALID_CHECK_IN_OTP",
                    message="Valid 6-digit customer check-in OTP is required.",
                )
            if auth_store is not None:
                await auth_store.clear_booking_otp_failures(otp_scope)
        booking.checked_in_at = now_utc
    elif target_status == BookingStatus.IN_SERVICE:
        booking.started_at = now_utc
    elif target_status == BookingStatus.COMPLETED:
        if actor_role != UserRole.ADMIN:
            otp_scope = f"{booking.id}:completion:{principal.user.id}"
            if auth_store is not None:
                locked_for = await auth_store.is_booking_otp_locked(
                    otp_scope, max_failures=settings.otp_verify_max_attempts
                )
                if locked_for is not None:
                    raise ChairAPIError(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        code="BOOKING_OTP_LOCKED",
                        message=f"Too many failed completion OTP attempts. Retry in {locked_for}s.",
                    )
            if not otp_code or not verify_booking_otp(
                settings, booking.id, "completion", otp_code, booking.completion_otp_hash
            ):
                if auth_store is not None:
                    await auth_store.record_booking_otp_failure(
                        otp_scope_key=otp_scope,
                        window_seconds=settings.otp_request_window_seconds,
                        max_failures=settings.otp_verify_max_attempts,
                    )
                raise ChairAPIError(
                    status_code=status.HTTP_403_FORBIDDEN,
                    code="INVALID_COMPLETION_OTP",
                    message="Valid 6-digit customer completion OTP is required.",
                )
            if auth_store is not None:
                await auth_store.clear_booking_otp_failures(otp_scope)
        booking.completed_at = now_utc
        await session.execute(
            update(BookingAllocation)
            .where(
                BookingAllocation.booking_id == booking.id,
                BookingAllocation.is_active.is_(True),
            )
            .values(is_active=False, updated_at=now_utc)
        )
        if booking.source == "PLATFORM":
            existing_ledger = await session.scalar(
                select(CommissionLedger).where(CommissionLedger.booking_id == booking.id)
            )
            if existing_ledger is None:
                branch = await session.scalar(select(Branch).where(Branch.id == booking.branch_id))
                rate_bps = settings.default_commission_rate_bps
                active_sub_rate = await session.scalar(
                    select(SubscriptionPlan.commission_rate_bps)
                    .join(Subscription, Subscription.plan_id == SubscriptionPlan.id)
                    .where(
                        Subscription.branch_id == booking.branch_id,
                        Subscription.status.in_(("ACTIVE", "TRIAL")),
                    )
                    .order_by(desc(Subscription.created_at))
                )
                if active_sub_rate is not None:
                    rate_bps = active_sub_rate
                commission_paise = (booking.net_payable_paise * rate_bps) // 10_000
                gst_paise = (commission_paise * settings.commission_gst_bps) // 10_000
                if branch is not None:
                    session.add(
                        CommissionLedger(
                            booking_id=booking.id,
                            salon_id=branch.salon_id,
                            branch_id=booking.branch_id,
                            gross_booking_paise=booking.net_payable_paise,
                            commission_rate_bps=rate_bps,
                            commission_paise=commission_paise,
                            gst_on_commission_paise=gst_paise,
                            eligibility_reason="COMPLETED_PLATFORM_BOOKING",
                            status="ACCRUED",
                        )
                    )
    elif target_status == BookingStatus.NO_SHOW:
        await session.execute(
            update(BookingAllocation)
            .where(
                BookingAllocation.booking_id == booking.id,
                BookingAllocation.is_active.is_(True),
            )
            .values(is_active=False, updated_at=now_utc)
        )

    booking.status = target_status.value
    await record_audit_log(
        session,
        actor_user_id=principal.user.id,
        actor_role=principal.primary_role,
        action=f"BOOKING_{target_status.value}",
        resource_type="booking",
        resource_id=str(booking.id),
        branch_id=booking.branch_id,
        after_state={"status": target_status.value},
        request_id=principal.request_id,
        ip_address=principal.ip_address,
    )
    await session.commit()
    return await serialize_booking_detail(
        session, booking=booking, settings=settings, include_customer_otps=False
    )


_ALLOWED_WALK_IN_TRANSITIONS: dict[WalkInStatus, frozenset[WalkInStatus]] = {
    WalkInStatus.WAITING: frozenset(
        {
            WalkInStatus.SEATED,
            WalkInStatus.IN_SERVICE,
            WalkInStatus.CANCELLED,
            WalkInStatus.NO_SHOW,
        }
    ),
    WalkInStatus.SEATED: frozenset(
        {
            WalkInStatus.IN_SERVICE,
            WalkInStatus.COMPLETED,
            WalkInStatus.CANCELLED,
            WalkInStatus.NO_SHOW,
        }
    ),
    WalkInStatus.IN_SERVICE: frozenset(
        {WalkInStatus.COMPLETED, WalkInStatus.CANCELLED}
    ),
    WalkInStatus.COMPLETED: frozenset(),
    WalkInStatus.CANCELLED: frozenset(),
    WalkInStatus.NO_SHOW: frozenset(),
}


async def update_walk_in_status(
    session: AsyncSession,
    *,
    branch_id: uuid.UUID,
    walk_in_id: uuid.UUID,
    target_status: WalkInStatus,
    staff_id: uuid.UUID | None,
    resource_id: uuid.UUID | None,
    principal: AuthPrincipal,
) -> WalkIn:
    """Update live walk-in queue item, enforcing branch ownership and slot exclusion."""
    now_utc = datetime.now(UTC)
    walk_in = await session.scalar(
        select(WalkIn)
        .where(WalkIn.id == walk_in_id, WalkIn.branch_id == branch_id)
        .with_for_update()
    )
    if walk_in is None:
        raise ChairAPIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="WALK_IN_NOT_FOUND",
            message="Walk-in entry was not found.",
        )

    current_wi_status = WalkInStatus(walk_in.status)
    if (
        target_status != current_wi_status
        and target_status not in _ALLOWED_WALK_IN_TRANSITIONS[current_wi_status]
    ):
        raise ChairAPIError(
            status_code=status.HTTP_409_CONFLICT,
            code="INVALID_WALK_IN_TRANSITION",
            message=f"Cannot move walk-in from '{current_wi_status}' to '{target_status}'.",
        )

    if staff_id is not None:
        valid_staff = await session.scalar(
            select(Staff).where(
                Staff.id == staff_id,
                Staff.branch_id == branch_id,
                Staff.status == "ACTIVE",
            )
        )
        if valid_staff is None:
            raise ChairAPIError(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                code="INVALID_STAFF_FOR_BRANCH",
                message="Selected staff member is not active in this branch.",
            )
        walk_in.staff_id = staff_id

    if resource_id is not None:
        valid_chair = await session.scalar(
            select(Resource).where(
                Resource.id == resource_id,
                Resource.branch_id == branch_id,
                Resource.is_active.is_(True),
            )
        )
        if valid_chair is None:
            raise ChairAPIError(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                code="INVALID_RESOURCE_FOR_BRANCH",
                message="Selected chair resource is not active in this branch.",
            )
        walk_in.resource_id = resource_id

    if target_status in (WalkInStatus.SEATED, WalkInStatus.IN_SERVICE):
        if walk_in.staff_id is None:
            raise ChairAPIError(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                code="STAFF_REQUIRED_FOR_SEATING",
                message="Assign an active barber before seating this walk-in guest.",
            )
        existing_alloc = await session.scalar(
            select(BookingAllocation).where(
                BookingAllocation.walk_in_id == walk_in.id,
                BookingAllocation.is_active.is_(True),
            )
        )
        target_range = (
            existing_alloc.allocated_range
            if existing_alloc is not None
            else Range(
                now_utc,
                now_utc + timedelta(minutes=walk_in.estimated_duration_minutes),
                bounds="[)",
            )
        )
        needs_allocation = existing_alloc is None or (
            existing_alloc.staff_id != walk_in.staff_id
            or existing_alloc.resource_id != walk_in.resource_id
        )
        if needs_allocation:
            try:
                async with session.begin_nested():
                    if existing_alloc is not None:
                        existing_alloc.is_active = False
                        existing_alloc.updated_at = now_utc
                        await session.flush()
                    if await _has_overlapping_capacity_demand(
                        session,
                        branch_id=branch_id,
                        staff_id=walk_in.staff_id,
                        resource_id=walk_in.resource_id,
                        interval_range=target_range,
                        now_utc=now_utc,
                        exclude_walk_in_id=walk_in.id,
                    ):
                        raise ChairAPIError(
                            status_code=status.HTTP_409_CONFLICT,
                            code="WALK_IN_SLOT_CONFLICT",
                            message="Selected barber or chair has an active hold or allocation.",
                        )
                    session.add(
                        BookingAllocation(
                            walk_in_id=walk_in.id,
                            branch_id=branch_id,
                            staff_id=walk_in.staff_id,
                            resource_id=walk_in.resource_id,
                            allocated_range=target_range,
                            is_active=True,
                        )
                    )
                    await session.flush()
            except IntegrityError as exc:
                raise ChairAPIError(
                    status_code=status.HTTP_409_CONFLICT,
                    code="WALK_IN_SLOT_CONFLICT",
                    message="Selected barber or chair is already occupied.",
                ) from exc

    if target_status in (WalkInStatus.COMPLETED, WalkInStatus.CANCELLED, WalkInStatus.NO_SHOW):
        walk_in.completed_at = now_utc
        await session.execute(
            update(BookingAllocation)
            .where(
                BookingAllocation.walk_in_id == walk_in.id,
                BookingAllocation.is_active.is_(True),
            )
            .values(is_active=False, updated_at=now_utc)
        )

    walk_in.status = target_status.value
    await record_audit_log(
        session,
        actor_user_id=principal.user.id,
        actor_role=principal.primary_role,
        action=f"WALK_IN_{target_status.value}",
        resource_type="walk_in",
        resource_id=str(walk_in.id),
        branch_id=branch_id,
        after_state={"status": walk_in.status},
        request_id=principal.request_id,
        ip_address=principal.ip_address,
    )
    await session.commit()
    return walk_in

"""Customer hold creation, booking checkout, cancellation, OTP retrieval, and reviews."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Header, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError

from chair_api.api.deps import DbSessionDep, PaymentProviderDep, SettingsDep
from chair_api.core.errors import ChairAPIError
from chair_api.db.models import Booking, Branch, Review, SlotHold
from chair_api.domain.enums import BookingStatus, UserRole
from chair_api.security.rbac import CurrentPrincipalDep
from chair_api.services.audit import record_audit_log
from chair_api.services.booking_engine import (
    cancel_booking_transaction,
    capture_test_mode_payment,
    confirm_booking_pay_at_salon,
    create_booking_payment_order,
    create_slot_hold_and_booking,
    expire_stale_holds,
    serialize_booking_detail,
)

router = APIRouter()


class CreateHoldRequest(BaseModel):
    branch_id: uuid.UUID
    branch_service_ids: list[uuid.UUID] = Field(min_length=1, max_length=5)
    start_at: datetime
    staff_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=500)


class TestPaymentCaptureRequest(BaseModel):
    provider_order_id: str = Field(min_length=3, max_length=128)


class CancelBookingRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class CreateReviewRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    hygiene_rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


@router.post("/holds")
async def create_hold(
    payload: CreateHoldRequest,
    principal: CurrentPrincipalDep,
    session: DbSessionDep,
    settings: SettingsDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    """Reserve a 5-minute slot hold + HELD booking atomically using PostgreSQL exclusion locks."""
    code, body = await create_slot_hold_and_booking(
        session,
        principal=principal,
        settings=settings,
        idempotency_key_raw=idempotency_key,
        branch_id=payload.branch_id,
        branch_service_ids=payload.branch_service_ids,
        start_at=payload.start_at,
        staff_id=payload.staff_id,
        notes=payload.notes,
    )
    return JSONResponse(status_code=code, content=body)


@router.get("/holds/{hold_id}")
async def get_hold_detail(
    hold_id: uuid.UUID,
    principal: CurrentPrincipalDep,
    session: DbSessionDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    """Return active/expired hold and linked booking checkout preview for the owning customer."""
    now_utc = datetime.now(UTC)
    await expire_stale_holds(session, hold_ids=[hold_id], now_utc=now_utc)
    hold = await session.scalar(select(SlotHold).where(SlotHold.id == hold_id))
    if hold is None or (
        hold.customer_user_id != principal.user.id and UserRole.ADMIN not in principal.role_set
    ):
        raise ChairAPIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="HOLD_NOT_FOUND",
            message="Slot hold was not found.",
        )

    booking = await session.scalar(
        select(Booking).where(Booking.slot_hold_id == hold.id).order_by(desc(Booking.created_at))
    )
    await session.commit()
    if booking is None:
        raise ChairAPIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="BOOKING_NOT_FOUND",
            message="Booking linked to hold was not found.",
        )

    detail = await serialize_booking_detail(
        session,
        booking=booking,
        settings=settings,
        include_customer_otps=(booking.customer_user_id == principal.user.id),
    )
    return {
        "hold_id": str(hold.id),
        "hold_status": hold.status,
        "expires_at": hold.expires_at.isoformat(),
        "hold_ttl_seconds": settings.booking_hold_ttl_seconds,
        "booking": detail,
    }


@router.delete("/holds/{hold_id}")
async def release_hold(
    hold_id: uuid.UUID,
    principal: CurrentPrincipalDep,
    session: DbSessionDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    """Release an active slot hold and cancel its unconfirmed HELD booking."""
    hold = await session.scalar(select(SlotHold).where(SlotHold.id == hold_id).with_for_update())
    if hold is None or (
        hold.customer_user_id != principal.user.id and UserRole.ADMIN not in principal.role_set
    ):
        raise ChairAPIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="HOLD_NOT_FOUND",
            message="Slot hold was not found.",
        )

    booking = await session.scalar(
        select(Booking)
        .where(Booking.slot_hold_id == hold.id)
        .order_by(Booking.id.asc())
        .with_for_update()
    )
    if booking is not None and booking.status == BookingStatus.HELD.value:
        _, body = await cancel_booking_transaction(
            session,
            booking_id=booking.id,
            actor_user_id=principal.user.id,
            actor_role=(
                UserRole.CUSTOMER
                if booking.customer_user_id == principal.user.id
                else UserRole.ADMIN
            ),
            actor_role_label=principal.primary_role,
            reason="Customer released hold",
            idempotency_key_raw=f"release-hold:{hold.id}",
            settings=settings,
            request_id=principal.request_id,
            ip_address=principal.ip_address,
        )
        return {"status": "RELEASED", "booking": body}

    now_utc = datetime.now(UTC)
    if hold.status == "ACTIVE":
        hold.status = "RELEASED"
        hold.updated_at = now_utc
        await session.commit()
    return {"status": hold.status}


@router.get("/bookings")
async def list_my_bookings(
    principal: CurrentPrincipalDep,
    session: DbSessionDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    """List customer's bookings newest first after sweeping any expired holds."""
    customer_id = principal.user.id
    rows = list(
        await session.scalars(
            select(Booking)
            .where(Booking.customer_user_id == customer_id)
            .order_by(desc(Booking.created_at))
            .limit(50)
        )
    )
    held_ids = [b.slot_hold_id for b in rows if b.slot_hold_id is not None]
    if held_ids:
        expired = await expire_stale_holds(session, hold_ids=held_ids)
        if expired:
            await session.commit()
            rows = list(
                await session.scalars(
                    select(Booking)
                    .where(Booking.customer_user_id == customer_id)
                    .order_by(desc(Booking.created_at))
                    .limit(50)
                    .execution_options(populate_existing=True)
                )
            )

    items = [
        await serialize_booking_detail(
            session, booking=row, settings=settings, include_customer_otps=True
        )
        for row in rows
    ]
    return {"items": items}


@router.get("/bookings/{booking_id}")
async def get_booking_detail(
    booking_id: uuid.UUID,
    principal: CurrentPrincipalDep,
    session: DbSessionDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    """Return authoritative customer booking detail including Check-In & Completion OTPs."""
    booking = await session.scalar(select(Booking).where(Booking.id == booking_id))
    if booking is None or (
        booking.customer_user_id != principal.user.id and UserRole.ADMIN not in principal.role_set
    ):
        raise ChairAPIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="BOOKING_NOT_FOUND",
            message="Booking was not found.",
        )

    if booking.slot_hold_id is not None and booking.status == BookingStatus.HELD.value:
        expired = await expire_stale_holds(session, hold_ids=[booking.slot_hold_id])
        if expired:
            await session.commit()
            await session.refresh(booking)

    return await serialize_booking_detail(
        session,
        booking=booking,
        settings=settings,
        include_customer_otps=(booking.customer_user_id == principal.user.id),
    )


@router.post("/bookings/{booking_id}/confirm-pay-at-salon")
async def confirm_pay_at_salon(
    booking_id: uuid.UUID,
    principal: CurrentPrincipalDep,
    session: DbSessionDep,
    settings: SettingsDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    """Confirm a HELD booking with Pay-at-Salon payment option."""
    code, body = await confirm_booking_pay_at_salon(
        session,
        principal=principal,
        settings=settings,
        booking_id=booking_id,
        idempotency_key_raw=idempotency_key,
    )
    return JSONResponse(status_code=code, content=body)


@router.post("/bookings/{booking_id}/payment-order")
async def create_payment_order(
    booking_id: uuid.UUID,
    principal: CurrentPrincipalDep,
    session: DbSessionDep,
    payment_provider: PaymentProviderDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    """Create a gateway payment order for online checkout."""
    code, body = await create_booking_payment_order(
        session,
        principal=principal,
        payment_provider=payment_provider,
        booking_id=booking_id,
        idempotency_key_raw=idempotency_key,
    )
    return JSONResponse(status_code=code, content=body)


@router.post("/bookings/{booking_id}/test-payment-capture")
async def test_mode_payment_capture(
    booking_id: uuid.UUID,
    payload: TestPaymentCaptureRequest,
    principal: CurrentPrincipalDep,
    session: DbSessionDep,
    settings: SettingsDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    """Simulate captured payment in TEST_MODE dev/test environments only."""
    code, body = await capture_test_mode_payment(
        session,
        principal=principal,
        settings=settings,
        booking_id=booking_id,
        provider_order_id=payload.provider_order_id,
        idempotency_key_raw=idempotency_key,
    )
    return JSONResponse(status_code=code, content=body)


@router.post("/bookings/{booking_id}/cancel")
async def cancel_customer_booking(
    booking_id: uuid.UUID,
    payload: CancelBookingRequest,
    principal: CurrentPrincipalDep,
    session: DbSessionDep,
    settings: SettingsDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    """Cancel customer's booking cleanly and auto-refund if payment was captured."""
    code, body = await cancel_booking_transaction(
        session,
        booking_id=booking_id,
        actor_user_id=principal.user.id,
        actor_role=UserRole.CUSTOMER,
        actor_role_label=principal.primary_role,
        reason=payload.reason,
        idempotency_key_raw=idempotency_key,
        settings=settings,
        request_id=principal.request_id,
        ip_address=principal.ip_address,
    )
    return JSONResponse(status_code=code, content=body)


@router.post("/bookings/{booking_id}/review", status_code=status.HTTP_201_CREATED)
async def create_booking_review(
    booking_id: uuid.UUID,
    payload: CreateReviewRequest,
    principal: CurrentPrincipalDep,
    session: DbSessionDep,
) -> dict[str, Any]:
    """Allow customer review submission strictly on owned COMPLETED bookings."""
    booking = await session.scalar(select(Booking).where(Booking.id == booking_id))
    if booking is None or booking.customer_user_id != principal.user.id:
        raise ChairAPIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="BOOKING_NOT_FOUND",
            message="Booking was not found.",
        )
    if booking.status != BookingStatus.COMPLETED.value:
        raise ChairAPIError(
            status_code=status.HTTP_409_CONFLICT,
            code="REVIEW_REQUIRES_COMPLETED_BOOKING",
            message="Reviews can only be submitted after the booking is completed.",
        )

    existing = await session.scalar(select(Review).where(Review.booking_id == booking.id))
    if existing is not None:
        raise ChairAPIError(
            status_code=status.HTTP_409_CONFLICT,
            code="REVIEW_ALREADY_EXISTS",
            message="A review has already been submitted for this booking.",
        )

    branch = await session.scalar(select(Branch).where(Branch.id == booking.branch_id))
    review = Review(
        booking_id=booking.id,
        customer_user_id=principal.user.id,
        branch_id=booking.branch_id,
        rating=payload.rating,
        hygiene_rating=payload.hygiene_rating,
        comment=(payload.comment or "").strip() or None,
        is_published=True,
    )
    session.add(review)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ChairAPIError(
            status_code=status.HTTP_409_CONFLICT,
            code="REVIEW_ALREADY_EXISTS",
            message="A review has already been submitted for this booking.",
        ) from exc

    await record_audit_log(
        session,
        actor_user_id=principal.user.id,
        actor_role=principal.primary_role,
        action="REVIEW_CREATED",
        resource_type="review",
        resource_id=str(review.id),
        branch_id=branch.id if branch else booking.branch_id,
        after_state={"rating": payload.rating, "hygiene_rating": payload.hygiene_rating},
        request_id=principal.request_id,
        ip_address=principal.ip_address,
    )
    await session.commit()
    return {
        "id": str(review.id),
        "booking_id": str(booking.id),
        "rating": review.rating,
        "hygiene_rating": review.hygiene_rating,
        "comment": review.comment,
        "created_at": review.created_at.isoformat(),
    }

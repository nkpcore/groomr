"""Partner-scoped workspace, tenant isolation, booking ops, walk-ins, and pause controls."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_, select

from chair_api.api.deps import AuthStoreDep, DbSessionDep, SettingsDep
from chair_api.core.errors import ChairAPIError
from chair_api.db.models import Booking, Branch, Resource, Salon, Staff, WalkIn
from chair_api.domain.enums import BookingStatus, UserRole, WalkInStatus
from chair_api.security.rbac import AuthPrincipal, assert_branch_access, require_roles
from chair_api.services.audit import record_audit_log
from chair_api.services.booking_engine import (
    cancel_booking_transaction,
    expire_stale_holds,
    serialize_booking_detail,
    transition_booking_partner,
    update_walk_in_status,
)

router = APIRouter()
PartnerPrincipalDep = Annotated[
    AuthPrincipal,
    Depends(require_roles(UserRole.PARTNER_OWNER, UserRole.PARTNER_STAFF)),
]


class PartnerSalonSummary(BaseModel):
    id: uuid.UUID
    brand_name: str
    legal_name: str
    status: str
    verification_badge_status: str


class PartnerBranchSummary(BaseModel):
    id: uuid.UUID
    salon_id: uuid.UUID
    name: str
    city: str
    state: str
    status: str
    verification_status: str
    online_booking_paused: bool


class PartnerContextResponse(BaseModel):
    salons: list[PartnerSalonSummary]
    branches: list[PartnerBranchSummary]


class BranchAccessResponse(BaseModel):
    branch_id: uuid.UUID
    salon_id: uuid.UUID
    name: str
    city: str
    status: str
    verification_status: str


@router.get("/context", response_model=PartnerContextResponse)
async def get_partner_context(
    principal: PartnerPrincipalDep,
    session: DbSessionDep,
) -> PartnerContextResponse:
    """Return salons and branches authorized for the signed-in partner user."""
    scoped_salon_ids = {
        scope.salon_id
        for scope in principal.roles
        if scope.salon_id is not None and scope.branch_id is None
    }
    scoped_branch_ids = {
        scope.branch_id for scope in principal.roles if scope.branch_id is not None
    }

    if UserRole.PARTNER_OWNER in principal.role_set:
        owned_salon_ids = list(
            await session.scalars(select(Salon.id).where(Salon.owner_user_id == principal.user.id))
        )
        scoped_salon_ids.update(owned_salon_ids)

    branch_filters = []
    if scoped_salon_ids:
        branch_filters.append(Branch.salon_id.in_(scoped_salon_ids))
    if scoped_branch_ids:
        branch_filters.append(Branch.id.in_(scoped_branch_ids))

    branches: list[Branch] = []
    if branch_filters:
        branches = list(
            await session.scalars(
                select(Branch).where(or_(*branch_filters)).order_by(Branch.created_at.asc())
            )
        )

    visible_salon_ids = set(scoped_salon_ids) | {branch.salon_id for branch in branches}
    salons: list[Salon] = []
    if visible_salon_ids:
        salons = list(
            await session.scalars(
                select(Salon).where(Salon.id.in_(visible_salon_ids)).order_by(Salon.created_at.asc())
            )
        )

    return PartnerContextResponse(
        salons=[
            PartnerSalonSummary(
                id=s.id,
                brand_name=s.brand_name,
                legal_name=s.legal_name,
                status=s.status,
                verification_badge_status=s.verification_badge_status,
            )
            for s in salons
        ],
        branches=[
            PartnerBranchSummary(
                id=b.id,
                salon_id=b.salon_id,
                name=b.name,
                city=b.city,
                state=b.state,
                status=b.status,
                verification_status=b.verification_status,
                online_booking_paused=b.online_booking_paused,
            )
            for b in branches
        ],
    )


@router.get("/branches/{branch_id}/access", response_model=BranchAccessResponse)
async def check_partner_branch_access(
    branch_id: uuid.UUID,
    principal: PartnerPrincipalDep,
    session: DbSessionDep,
) -> BranchAccessResponse:
    """Verify tenant isolation for a specific branch owned/managed by this partner."""
    branch = await assert_branch_access(session, principal, branch_id)
    return BranchAccessResponse(
        branch_id=branch.id,
        salon_id=branch.salon_id,
        name=branch.name,
        city=branch.city,
        status=branch.status,
        verification_status=branch.verification_status,
    )


class PartnerOtpTransitionRequest(BaseModel):
    otp_code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class PartnerCancelBookingRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class BranchPauseRequest(BaseModel):
    paused: bool


class CreateWalkInRequest(BaseModel):
    customer_name: str = Field(min_length=1, max_length=120)
    customer_phone_e164: str | None = Field(default=None, max_length=20)
    service_summary: str = Field(min_length=2, max_length=255)
    quoted_price_paise: int = Field(ge=0, le=5_000_000)
    estimated_duration_minutes: int = Field(ge=5, le=360)
    staff_id: uuid.UUID | None = None
    resource_id: uuid.UUID | None = None


class UpdateWalkInRequest(BaseModel):
    status: WalkInStatus
    staff_id: uuid.UUID | None = None
    resource_id: uuid.UUID | None = None


def _serialize_walk_in(w: WalkIn) -> dict[str, Any]:
    return {
        "id": str(w.id),
        "branch_id": str(w.branch_id),
        "staff_id": str(w.staff_id) if w.staff_id else None,
        "resource_id": str(w.resource_id) if w.resource_id else None,
        "customer_name": w.customer_name,
        "customer_phone_e164": w.customer_phone_e164,
        "service_summary": w.service_summary,
        "quoted_price_paise": w.quoted_price_paise,
        "estimated_duration_minutes": w.estimated_duration_minutes,
        "queue_position": w.queue_position,
        "status": w.status,
        "checked_in_at": w.checked_in_at.isoformat(),
        "completed_at": w.completed_at.isoformat() if w.completed_at else None,
    }


@router.patch("/branches/{branch_id}/pause")
async def set_branch_online_pause(
    branch_id: uuid.UUID,
    payload: BranchPauseRequest,
    principal: PartnerPrincipalDep,
    session: DbSessionDep,
) -> dict[str, Any]:
    """Pause or resume online slot bookings for an authorized branch."""
    branch = await assert_branch_access(session, principal, branch_id)
    prev = branch.online_booking_paused
    branch.online_booking_paused = payload.paused
    await record_audit_log(
        session,
        actor_user_id=principal.user.id,
        actor_role=principal.primary_role,
        action="BRANCH_PAUSE_UPDATED",
        resource_type="branch",
        resource_id=str(branch.id),
        branch_id=branch.id,
        before_state={"online_booking_paused": prev},
        after_state={"online_booking_paused": payload.paused},
        request_id=principal.request_id,
        ip_address=principal.ip_address,
    )
    await session.commit()
    return {"branch_id": str(branch.id), "online_booking_paused": branch.online_booking_paused}


@router.get("/branches/{branch_id}/bookings")
async def list_partner_branch_bookings(
    branch_id: uuid.UUID,
    principal: PartnerPrincipalDep,
    session: DbSessionDep,
    settings: SettingsDep,
    status_filter: Annotated[BookingStatus | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    """List bookings scoped to an authorized partner branch (never exposing customer OTPs)."""
    await assert_branch_access(session, principal, branch_id)
    await expire_stale_holds(session, branch_id=branch_id)
    stmt = (
        select(Booking)
        .where(Booking.branch_id == branch_id)
        .order_by(desc(Booking.scheduled_start_at))
        .limit(50)
    )
    if status_filter is not None:
        stmt = stmt.where(Booking.status == status_filter.value)
    rows = list(await session.scalars(stmt))
    await session.commit()
    items = [
        await serialize_booking_detail(
            session, booking=row, settings=settings, include_customer_otps=False
        )
        for row in rows
    ]
    return {"items": items}


@router.post("/branches/{branch_id}/bookings/{booking_id}/check-in")
async def partner_check_in_booking(
    branch_id: uuid.UUID,
    booking_id: uuid.UUID,
    payload: PartnerOtpTransitionRequest,
    principal: PartnerPrincipalDep,
    session: DbSessionDep,
    settings: SettingsDep,
    auth_store: AuthStoreDep,
) -> dict[str, Any]:
    """Move CONFIRMED booking to CHECKED_IN after verifying 6-digit customer OTP."""
    await assert_branch_access(session, principal, branch_id)
    return await transition_booking_partner(
        session,
        branch_id=branch_id,
        booking_id=booking_id,
        target_status=BookingStatus.CHECKED_IN,
        principal=principal,
        settings=settings,
        otp_code=payload.otp_code,
        auth_store=auth_store,
    )


@router.post("/branches/{branch_id}/bookings/{booking_id}/start")
async def partner_start_booking(
    branch_id: uuid.UUID,
    booking_id: uuid.UUID,
    principal: PartnerPrincipalDep,
    session: DbSessionDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    """Move CHECKED_IN booking to IN_SERVICE."""
    await assert_branch_access(session, principal, branch_id)
    return await transition_booking_partner(
        session,
        branch_id=branch_id,
        booking_id=booking_id,
        target_status=BookingStatus.IN_SERVICE,
        principal=principal,
        settings=settings,
    )


@router.post("/branches/{branch_id}/bookings/{booking_id}/complete")
async def partner_complete_booking(
    branch_id: uuid.UUID,
    booking_id: uuid.UUID,
    payload: PartnerOtpTransitionRequest,
    principal: PartnerPrincipalDep,
    session: DbSessionDep,
    settings: SettingsDep,
    auth_store: AuthStoreDep,
) -> dict[str, Any]:
    """Complete IN_SERVICE booking with customer completion OTP and accrue commission."""
    await assert_branch_access(session, principal, branch_id)
    return await transition_booking_partner(
        session,
        branch_id=branch_id,
        booking_id=booking_id,
        target_status=BookingStatus.COMPLETED,
        principal=principal,
        settings=settings,
        otp_code=payload.otp_code,
        auth_store=auth_store,
    )


@router.post("/branches/{branch_id}/bookings/{booking_id}/no-show")
async def partner_mark_no_show(
    branch_id: uuid.UUID,
    booking_id: uuid.UUID,
    principal: PartnerPrincipalDep,
    session: DbSessionDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    """Mark CONFIRMED booking as NO_SHOW and free the chair/barber allocation."""
    await assert_branch_access(session, principal, branch_id)
    return await transition_booking_partner(
        session,
        branch_id=branch_id,
        booking_id=booking_id,
        target_status=BookingStatus.NO_SHOW,
        principal=principal,
        settings=settings,
    )


@router.post("/branches/{branch_id}/bookings/{booking_id}/cancel")
async def partner_cancel_booking(
    branch_id: uuid.UUID,
    booking_id: uuid.UUID,
    payload: PartnerCancelBookingRequest,
    principal: PartnerPrincipalDep,
    session: DbSessionDep,
    settings: SettingsDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    """Cancel booking from Partner desk and auto-refund any captured online payment."""
    await assert_branch_access(session, principal, branch_id)
    actor_role = (
        UserRole.PARTNER_OWNER
        if UserRole.PARTNER_OWNER in principal.role_set
        else UserRole.PARTNER_STAFF
    )
    code, body = await cancel_booking_transaction(
        session,
        booking_id=booking_id,
        actor_user_id=principal.user.id,
        actor_role=actor_role,
        actor_role_label=principal.primary_role,
        reason=payload.reason,
        idempotency_key_raw=idempotency_key,
        settings=settings,
        branch_id_scope=branch_id,
        request_id=principal.request_id,
        ip_address=principal.ip_address,
    )
    return JSONResponse(status_code=code, content=body)


@router.get("/branches/{branch_id}/walk-ins")
async def list_branch_walk_ins(
    branch_id: uuid.UUID,
    principal: PartnerPrincipalDep,
    session: DbSessionDep,
) -> dict[str, Any]:
    """List branch walk-ins sorted by active queue position."""
    await assert_branch_access(session, principal, branch_id)
    rows = list(
        await session.scalars(
            select(WalkIn)
            .where(WalkIn.branch_id == branch_id)
            .order_by(WalkIn.queue_position.desc(), WalkIn.checked_in_at.desc())
            .limit(50)
        )
    )
    return {"items": [_serialize_walk_in(w) for w in rows]}


@router.post("/branches/{branch_id}/walk-ins", status_code=status.HTTP_201_CREATED)
async def create_branch_walk_in(
    branch_id: uuid.UUID,
    payload: CreateWalkInRequest,
    principal: PartnerPrincipalDep,
    session: DbSessionDep,
) -> dict[str, Any]:
    """Check in a walk-in guest onto the live branch queue."""
    await assert_branch_access(session, principal, branch_id)
    if payload.staff_id is not None:
        staff_row = await session.scalar(
            select(Staff).where(Staff.id == payload.staff_id, Staff.branch_id == branch_id)
        )
        if staff_row is None:
            raise ChairAPIError(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                code="INVALID_STAFF_FOR_BRANCH",
                message="Selected staff member does not belong to this branch.",
            )
    if payload.resource_id is not None:
        chair_row = await session.scalar(
            select(Resource).where(
                Resource.id == payload.resource_id, Resource.branch_id == branch_id
            )
        )
        if chair_row is None:
            raise ChairAPIError(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                code="INVALID_RESOURCE_FOR_BRANCH",
                message="Selected chair resource does not belong to this branch.",
            )

    max_pos = int(
        await session.scalar(
            select(func.coalesce(func.max(WalkIn.queue_position), 0)).where(
                WalkIn.branch_id == branch_id
            )
        )
        or 0
    )
    now_utc = datetime.now(UTC)
    walk_in = WalkIn(
        branch_id=branch_id,
        staff_id=payload.staff_id,
        resource_id=payload.resource_id,
        customer_name=payload.customer_name.strip(),
        customer_phone_e164=(payload.customer_phone_e164 or "").strip() or None,
        service_summary=payload.service_summary.strip(),
        quoted_price_paise=payload.quoted_price_paise,
        estimated_duration_minutes=payload.estimated_duration_minutes,
        queue_position=max_pos + 1,
        status=WalkInStatus.WAITING.value,
        checked_in_at=now_utc,
    )
    session.add(walk_in)
    await session.flush()
    await record_audit_log(
        session,
        actor_user_id=principal.user.id,
        actor_role=principal.primary_role,
        action="WALK_IN_CREATED",
        resource_type="walk_in",
        resource_id=str(walk_in.id),
        branch_id=branch_id,
        after_state={"queue_position": walk_in.queue_position},
        request_id=principal.request_id,
        ip_address=principal.ip_address,
    )
    await session.commit()
    return _serialize_walk_in(walk_in)


@router.patch("/branches/{branch_id}/walk-ins/{walk_in_id}")
async def patch_branch_walk_in(
    branch_id: uuid.UUID,
    walk_in_id: uuid.UUID,
    payload: UpdateWalkInRequest,
    principal: PartnerPrincipalDep,
    session: DbSessionDep,
) -> dict[str, Any]:
    """Update walk-in status (SEATED/IN_SERVICE/COMPLETED/CANCELLED/NO_SHOW)."""
    await assert_branch_access(session, principal, branch_id)
    walk_in = await update_walk_in_status(
        session,
        branch_id=branch_id,
        walk_in_id=walk_in_id,
        target_status=payload.status,
        staff_id=payload.staff_id,
        resource_id=payload.resource_id,
        principal=principal,
    )
    return _serialize_walk_in(walk_in)

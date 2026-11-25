"""Partner-scoped workspace, tenant isolation, booking ops, walk-ins, and pause controls."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import desc, func, or_, select
from sqlalchemy.exc import IntegrityError

from chair_api.api.deps import AuthStoreDep, DbSessionDep, SettingsDep, StorageProviderDep
from chair_api.core.errors import ChairAPIError
from chair_api.db.models import (
    Booking,
    Branch,
    BranchService,
    Resource,
    Salon,
    ScheduleBlock,
    Service,
    Staff,
    WalkIn,
)
from chair_api.domain.enums import (
    BookingStatus,
    DocumentType,
    ResourceType,
    ScheduleBlockType,
    StaffStatus,
    UserRole,
    WalkInStatus,
)
from chair_api.security.rbac import (
    AuthPrincipal,
    CurrentPrincipalDep,
    assert_branch_access,
    assert_salon_access,
    require_roles,
)
from chair_api.services.audit import record_audit_log
from chair_api.services.booking_engine import (
    cancel_booking_transaction,
    expire_stale_holds,
    serialize_booking_detail,
    transition_booking_partner,
    update_walk_in_status,
)
from chair_api.services.partner_ops import (
    create_branch_for_salon,
    create_branch_schedule_block,
    load_branch_setup_state,
    onboard_salon_with_branch,
    serialize_document_row,
    upload_branch_kyc_document,
    upsert_staff_qualifications_and_shifts,
    validate_operating_hours,
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

    @field_validator("customer_name", "service_summary", mode="before")
    @classmethod
    def _strip_required_walk_in(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


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


class OnboardSalonRequest(BaseModel):
    legal_name: str = Field(min_length=2, max_length=180)
    brand_name: str = Field(min_length=2, max_length=180)
    gstin: str | None = Field(default=None, max_length=20)
    pan_masked: str | None = Field(default=None, max_length=20)
    branch_name: str = Field(min_length=2, max_length=160)
    address_line1: str = Field(min_length=4, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    city: str = Field(min_length=2, max_length=80)
    state: str = Field(min_length=2, max_length=80)
    pincode: str = Field(min_length=4, max_length=12)
    lat: float = Field(ge=-90.0, le=90.0)
    lng: float = Field(ge=-180.0, le=180.0)
    operating_hours: dict[str, dict[str, str] | None] | None = None
    initial_chair_count: int = Field(default=2, ge=0, le=50)

    @field_validator(
        "legal_name",
        "brand_name",
        "branch_name",
        "address_line1",
        "city",
        "state",
        "pincode",
        mode="before",
    )
    @classmethod
    def _strip_required_fields(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("pan_masked", mode="before")
    @classmethod
    def _validate_pan_masked(cls, value: Any) -> Any:
        if value is None:
            return None
        cleaned = str(value).strip()
        if not cleaned:
            return None
        if "*" not in cleaned:
            raise ValueError("pan_masked must be masked (e.g., ABCDE****F).")
        return cleaned


class CreateBranchRequest(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    address_line1: str = Field(min_length=4, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    city: str = Field(min_length=2, max_length=80)
    state: str = Field(min_length=2, max_length=80)
    pincode: str = Field(min_length=4, max_length=12)
    lat: float = Field(ge=-90.0, le=90.0)
    lng: float = Field(ge=-180.0, le=180.0)
    operating_hours: dict[str, dict[str, str] | None] | None = None
    initial_chair_count: int = Field(default=2, ge=0, le=50)

    @field_validator("name", "address_line1", "city", "state", "pincode", mode="before")
    @classmethod
    def _strip_required_fields(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class UpdateHoursRequest(BaseModel):
    operating_hours: dict[str, dict[str, str] | None]


class CreateBranchServiceRequest(BaseModel):
    service_id: uuid.UUID
    display_name_en: str = Field(min_length=2, max_length=140)
    display_name_hi: str = Field(min_length=2, max_length=140)
    description: str | None = Field(default=None, max_length=500)
    price_paise: int = Field(ge=0, le=10_000_000)
    duration_minutes: int = Field(ge=5, le=360)
    buffer_before_minutes: int = Field(default=0, ge=0, le=60)
    buffer_after_minutes: int = Field(default=5, ge=0, le=60)
    is_active: bool = True

    @field_validator("display_name_en", "display_name_hi", mode="before")
    @classmethod
    def _strip_required_fields(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class UpdateBranchServiceRequest(BaseModel):
    display_name_en: str | None = Field(default=None, min_length=2, max_length=140)
    display_name_hi: str | None = Field(default=None, min_length=2, max_length=140)
    description: str | None = Field(default=None, max_length=500)
    price_paise: int | None = Field(default=None, ge=0, le=10_000_000)
    duration_minutes: int | None = Field(default=None, ge=5, le=360)
    buffer_before_minutes: int | None = Field(default=None, ge=0, le=60)
    buffer_after_minutes: int | None = Field(default=None, ge=0, le=60)
    is_active: bool | None = None

    @field_validator("display_name_en", "display_name_hi", mode="before")
    @classmethod
    def _strip_optional_fields(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class StaffShiftInput(BaseModel):
    weekday: int = Field(ge=0, le=6)
    start_time: str
    end_time: str
    timezone: str = Field(default="Asia/Kolkata", min_length=3, max_length=64)


class CreateStaffRequest(BaseModel):
    display_name: str = Field(min_length=2, max_length=120)
    bio: str | None = Field(default=None, max_length=600)
    specializations: list[str] = Field(default_factory=list, max_length=12)
    is_accepting_bookings: bool = True
    status: StaffStatus = StaffStatus.ACTIVE
    qualified_branch_service_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    shifts: list[StaffShiftInput] = Field(default_factory=list, max_length=21)

    @field_validator("display_name", mode="before")
    @classmethod
    def _strip_display_name(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class UpdateStaffRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=2, max_length=120)
    bio: str | None = Field(default=None, max_length=600)
    specializations: list[str] | None = Field(default=None, max_length=12)
    is_accepting_bookings: bool | None = None
    status: StaffStatus | None = None
    qualified_branch_service_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)
    shifts: list[StaffShiftInput] | None = Field(default=None, max_length=21)

    @field_validator("display_name", mode="before")
    @classmethod
    def _strip_display_name(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class CreateScheduleBlockRequest(BaseModel):
    staff_id: uuid.UUID | None = None
    block_type: ScheduleBlockType
    start_at: datetime
    end_at: datetime
    reason: str | None = Field(default=None, max_length=255)


class CreateResourceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    resource_type: ResourceType = ResourceType.BARBER_CHAIR
    is_active: bool = True

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class UpdateResourceRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    resource_type: ResourceType | None = None
    is_active: bool | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class UploadDocumentRequest(BaseModel):
    document_type: DocumentType
    mime_type: str = Field(min_length=5, max_length=120)
    content_base64: str = Field(min_length=4, max_length=12_000_000)


@router.get("/catalog-services")
async def list_partner_catalog_services(
    _principal: CurrentPrincipalDep,
    session: DbSessionDep,
) -> dict[str, Any]:
    """List active canonical catalog service templates for branch menu setup."""
    services = list(
        await session.scalars(
            select(Service).where(Service.is_active.is_(True)).order_by(Service.name_en.asc())
        )
    )
    return {
        "items": [
            {
                "id": str(svc.id),
                "code": svc.code,
                "name_en": svc.name_en,
                "name_hi": svc.name_hi,
                "category": svc.category,
                "default_duration_minutes": svc.default_duration_minutes,
            }
            for svc in services
        ]
    }


@router.post("/salons", status_code=status.HTTP_201_CREATED)
async def register_partner_salon(
    payload: OnboardSalonRequest,
    principal: CurrentPrincipalDep,
    session: DbSessionDep,
) -> dict[str, Any]:
    """Register a salon and initial PostGIS branch, granting scoped PARTNER_OWNER access."""
    salon, branch = await onboard_salon_with_branch(
        session,
        principal=principal,
        legal_name=payload.legal_name,
        brand_name=payload.brand_name,
        gstin=payload.gstin,
        pan_masked=payload.pan_masked,
        branch_name=payload.branch_name,
        address_line1=payload.address_line1,
        address_line2=payload.address_line2,
        city=payload.city,
        state=payload.state,
        pincode=payload.pincode,
        lat=payload.lat,
        lng=payload.lng,
        operating_hours=payload.operating_hours,
        initial_chair_count=payload.initial_chair_count,
    )
    return {
        "salon": {
            "id": str(salon.id),
            "legal_name": salon.legal_name,
            "brand_name": salon.brand_name,
            "status": salon.status,
            "verification_badge_status": salon.verification_badge_status,
        },
        "branch": {
            "id": str(branch.id),
            "salon_id": str(branch.salon_id),
            "name": branch.name,
            "slug": branch.slug,
            "city": branch.city,
            "state": branch.state,
            "status": branch.status,
            "verification_status": branch.verification_status,
        },
    }


@router.post("/salons/{salon_id}/branches", status_code=status.HTTP_201_CREATED)
async def add_salon_branch(
    salon_id: uuid.UUID,
    payload: CreateBranchRequest,
    principal: PartnerPrincipalDep,
    session: DbSessionDep,
) -> dict[str, Any]:
    """Add a new draft branch to a salon owned by this partner."""
    salon = await assert_salon_access(
        session, principal, salon_id, allowed_roles=(UserRole.PARTNER_OWNER,)
    )
    branch = await create_branch_for_salon(
        session,
        principal=principal,
        salon=salon,
        branch_name=payload.name,
        address_line1=payload.address_line1,
        address_line2=payload.address_line2,
        city=payload.city,
        state=payload.state,
        pincode=payload.pincode,
        lat=payload.lat,
        lng=payload.lng,
        operating_hours=payload.operating_hours,
        initial_chair_count=payload.initial_chair_count,
    )
    return {
        "id": str(branch.id),
        "salon_id": str(branch.salon_id),
        "name": branch.name,
        "slug": branch.slug,
        "city": branch.city,
        "state": branch.state,
        "status": branch.status,
        "verification_status": branch.verification_status,
    }


@router.get("/branches/{branch_id}/setup")
async def get_branch_setup(
    branch_id: uuid.UUID,
    principal: PartnerPrincipalDep,
    session: DbSessionDep,
    storage: StorageProviderDep,
) -> dict[str, Any]:
    """Return full shop setup state, shifts, blocks, chairs, KYC docs, and inspection state."""
    await assert_branch_access(session, principal, branch_id)
    return await load_branch_setup_state(
        session, branch_id=branch_id, storage=storage, principal=principal
    )


@router.patch("/branches/{branch_id}/hours")
async def update_branch_operating_hours(
    branch_id: uuid.UUID,
    payload: UpdateHoursRequest,
    principal: PartnerPrincipalDep,
    session: DbSessionDep,
) -> dict[str, Any]:
    """Update operating hours (mon..sun) for an authorized branch."""
    branch = await assert_branch_access(session, principal, branch_id)
    normalized = validate_operating_hours(payload.operating_hours)
    branch.operating_hours_json = normalized
    await record_audit_log(
        session,
        actor_user_id=principal.user.id,
        actor_role=principal.primary_role,
        action="BRANCH_HOURS_UPDATED",
        resource_type="branch",
        resource_id=str(branch.id),
        branch_id=branch.id,
        after_state={"operating_hours": normalized},
        request_id=principal.request_id,
        ip_address=principal.ip_address,
    )
    await session.commit()
    return {"branch_id": str(branch.id), "operating_hours_json": branch.operating_hours_json}


@router.post("/branches/{branch_id}/services", status_code=status.HTTP_201_CREATED)
async def create_branch_service(
    branch_id: uuid.UUID,
    payload: CreateBranchServiceRequest,
    principal: PartnerPrincipalDep,
    session: DbSessionDep,
) -> dict[str, Any]:
    """Add a service offering (priced in integer paise) to an authorized branch."""
    await assert_branch_access(session, principal, branch_id)
    svc = await session.scalar(
        select(Service).where(Service.id == payload.service_id, Service.is_active.is_(True))
    )
    if svc is None:
        raise ChairAPIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="CATALOG_SERVICE_NOT_FOUND",
            message="Catalog service was not found or is inactive.",
        )
    existing = await session.scalar(
        select(BranchService).where(
            BranchService.branch_id == branch_id,
            BranchService.service_id == payload.service_id,
        )
    )
    if existing is not None:
        raise ChairAPIError(
            status_code=status.HTTP_409_CONFLICT,
            code="DUPLICATE_BRANCH_SERVICE",
            message="This catalog service is already configured for this branch.",
        )
    bs = BranchService(
        branch_id=branch_id,
        service_id=svc.id,
        display_name_en=payload.display_name_en.strip(),
        display_name_hi=payload.display_name_hi.strip(),
        description=(payload.description or "").strip() or None,
        price_paise=payload.price_paise,
        duration_minutes=payload.duration_minutes,
        buffer_before_minutes=payload.buffer_before_minutes,
        buffer_after_minutes=payload.buffer_after_minutes,
        is_active=payload.is_active,
    )
    try:
        async with session.begin_nested():
            session.add(bs)
            await session.flush()
    except IntegrityError as exc:
        raise ChairAPIError(
            status_code=status.HTTP_409_CONFLICT,
            code="DUPLICATE_BRANCH_SERVICE",
            message="This catalog service is already configured for this branch.",
        ) from exc
    await record_audit_log(
        session,
        actor_user_id=principal.user.id,
        actor_role=principal.primary_role,
        action="BRANCH_SERVICE_CREATED",
        resource_type="branch_service",
        resource_id=str(bs.id),
        branch_id=branch_id,
        after_state={"price_paise": bs.price_paise, "duration_minutes": bs.duration_minutes},
        request_id=principal.request_id,
        ip_address=principal.ip_address,
    )
    await session.commit()
    return {
        "id": str(bs.id),
        "service_id": str(bs.service_id),
        "code": svc.code,
        "category": svc.category,
        "display_name_en": bs.display_name_en,
        "display_name_hi": bs.display_name_hi,
        "description": bs.description,
        "price_paise": bs.price_paise,
        "duration_minutes": bs.duration_minutes,
        "buffer_before_minutes": bs.buffer_before_minutes,
        "buffer_after_minutes": bs.buffer_after_minutes,
        "is_active": bs.is_active,
    }


@router.patch("/branches/{branch_id}/services/{branch_service_id}")
async def update_branch_service(
    branch_id: uuid.UUID,
    branch_service_id: uuid.UUID,
    payload: UpdateBranchServiceRequest,
    principal: PartnerPrincipalDep,
    session: DbSessionDep,
) -> dict[str, Any]:
    """Update pricing, duration, buffers, or active flag for a branch service."""
    await assert_branch_access(session, principal, branch_id)
    row = (
        await session.execute(
            select(BranchService, Service.code, Service.category)
            .join(Service, Service.id == BranchService.service_id)
            .where(BranchService.id == branch_service_id, BranchService.branch_id == branch_id)
        )
    ).first()
    if row is None:
        raise ChairAPIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="BRANCH_SERVICE_NOT_FOUND",
            message="Branch service not found.",
        )
    bs, code, category = row
    if payload.display_name_en is not None:
        bs.display_name_en = payload.display_name_en.strip()
    if payload.display_name_hi is not None:
        bs.display_name_hi = payload.display_name_hi.strip()
    if payload.description is not None:
        bs.description = payload.description.strip() or None
    if payload.price_paise is not None:
        bs.price_paise = payload.price_paise
    if payload.duration_minutes is not None:
        bs.duration_minutes = payload.duration_minutes
    if payload.buffer_before_minutes is not None:
        bs.buffer_before_minutes = payload.buffer_before_minutes
    if payload.buffer_after_minutes is not None:
        bs.buffer_after_minutes = payload.buffer_after_minutes
    if payload.is_active is not None:
        bs.is_active = payload.is_active

    await record_audit_log(
        session,
        actor_user_id=principal.user.id,
        actor_role=principal.primary_role,
        action="BRANCH_SERVICE_UPDATED",
        resource_type="branch_service",
        resource_id=str(bs.id),
        branch_id=branch_id,
        after_state={"price_paise": bs.price_paise, "is_active": bs.is_active},
        request_id=principal.request_id,
        ip_address=principal.ip_address,
    )
    await session.commit()
    return {
        "id": str(bs.id),
        "service_id": str(bs.service_id),
        "code": code,
        "category": category,
        "display_name_en": bs.display_name_en,
        "display_name_hi": bs.display_name_hi,
        "description": bs.description,
        "price_paise": bs.price_paise,
        "duration_minutes": bs.duration_minutes,
        "buffer_before_minutes": bs.buffer_before_minutes,
        "buffer_after_minutes": bs.buffer_after_minutes,
        "is_active": bs.is_active,
    }


@router.post("/branches/{branch_id}/staff", status_code=status.HTTP_201_CREATED)
async def create_branch_staff(
    branch_id: uuid.UUID,
    payload: CreateStaffRequest,
    principal: PartnerPrincipalDep,
    session: DbSessionDep,
) -> dict[str, Any]:
    """Create a barber profile with branch-scoped service qualifications and shifts."""
    await assert_branch_access(session, principal, branch_id)
    staff = Staff(
        branch_id=branch_id,
        display_name=payload.display_name.strip(),
        bio=(payload.bio or "").strip() or None,
        specializations_json=[s.strip() for s in payload.specializations if s.strip()],
        is_verified_staff=False,
        is_accepting_bookings=payload.is_accepting_bookings,
        status=payload.status.value,
    )
    session.add(staff)
    await session.flush()

    await upsert_staff_qualifications_and_shifts(
        session,
        branch_id=branch_id,
        staff=staff,
        qualified_branch_service_ids=payload.qualified_branch_service_ids,
        shifts=[sh.model_dump() for sh in payload.shifts],
    )
    await record_audit_log(
        session,
        actor_user_id=principal.user.id,
        actor_role=principal.primary_role,
        action="STAFF_CREATED",
        resource_type="staff",
        resource_id=str(staff.id),
        branch_id=branch_id,
        after_state={"display_name": staff.display_name, "shift_count": len(payload.shifts)},
        request_id=principal.request_id,
        ip_address=principal.ip_address,
    )
    await session.commit()
    return {
        "id": str(staff.id),
        "branch_id": str(staff.branch_id),
        "display_name": staff.display_name,
        "status": staff.status,
        "is_accepting_bookings": staff.is_accepting_bookings,
    }


@router.patch("/branches/{branch_id}/staff/{staff_id}")
async def update_branch_staff(
    branch_id: uuid.UUID,
    staff_id: uuid.UUID,
    payload: UpdateStaffRequest,
    principal: PartnerPrincipalDep,
    session: DbSessionDep,
) -> dict[str, Any]:
    """Update barber profile, status, qualified services, or weekly shifts."""
    await assert_branch_access(session, principal, branch_id)
    staff = await session.scalar(
        select(Staff).where(Staff.id == staff_id, Staff.branch_id == branch_id)
    )
    if staff is None:
        raise ChairAPIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="STAFF_NOT_FOUND",
            message="Staff member not found in this branch.",
        )
    if payload.display_name is not None:
        staff.display_name = payload.display_name.strip()
    if payload.bio is not None:
        staff.bio = payload.bio.strip() or None
    if payload.specializations is not None:
        staff.specializations_json = [s.strip() for s in payload.specializations if s.strip()]
    if payload.is_accepting_bookings is not None:
        staff.is_accepting_bookings = payload.is_accepting_bookings
    if payload.status is not None:
        staff.status = payload.status.value

    await upsert_staff_qualifications_and_shifts(
        session,
        branch_id=branch_id,
        staff=staff,
        qualified_branch_service_ids=payload.qualified_branch_service_ids,
        shifts=(
            [sh.model_dump() for sh in payload.shifts] if payload.shifts is not None else None
        ),
    )
    await record_audit_log(
        session,
        actor_user_id=principal.user.id,
        actor_role=principal.primary_role,
        action="STAFF_UPDATED",
        resource_type="staff",
        resource_id=str(staff.id),
        branch_id=branch_id,
        after_state={"display_name": staff.display_name, "status": staff.status},
        request_id=principal.request_id,
        ip_address=principal.ip_address,
    )
    await session.commit()
    return {
        "id": str(staff.id),
        "branch_id": str(staff.branch_id),
        "display_name": staff.display_name,
        "status": staff.status,
        "is_accepting_bookings": staff.is_accepting_bookings,
    }


@router.post("/branches/{branch_id}/blocks", status_code=status.HTTP_201_CREATED)
async def create_schedule_block(
    branch_id: uuid.UUID,
    payload: CreateScheduleBlockRequest,
    principal: PartnerPrincipalDep,
    session: DbSessionDep,
) -> dict[str, Any]:
    """Block a branch or barber window (BREAK/LEAVE/HOLIDAY/MAINTENANCE)."""
    await assert_branch_access(session, principal, branch_id)
    block = await create_branch_schedule_block(
        session,
        principal=principal,
        branch_id=branch_id,
        staff_id=payload.staff_id,
        block_type=payload.block_type,
        start_at=payload.start_at,
        end_at=payload.end_at,
        reason=payload.reason,
    )
    return {
        "id": str(block.id),
        "branch_id": str(block.branch_id),
        "staff_id": str(block.staff_id) if block.staff_id else None,
        "block_type": block.block_type,
        "start_at": (
            block.blocked_range.lower.astimezone(UTC).isoformat()
            if block.blocked_range.lower is not None
            else ""
        ),
        "end_at": (
            block.blocked_range.upper.astimezone(UTC).isoformat()
            if block.blocked_range.upper is not None
            else ""
        ),
        "reason": block.reason,
    }


@router.delete("/branches/{branch_id}/blocks/{block_id}")
async def delete_schedule_block(
    branch_id: uuid.UUID,
    block_id: uuid.UUID,
    principal: PartnerPrincipalDep,
    session: DbSessionDep,
) -> dict[str, Any]:
    """Remove a schedule block scoped to an authorized partner branch."""
    await assert_branch_access(session, principal, branch_id)
    block = await session.scalar(
        select(ScheduleBlock).where(
            ScheduleBlock.id == block_id, ScheduleBlock.branch_id == branch_id
        )
    )
    if block is None:
        raise ChairAPIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="SCHEDULE_BLOCK_NOT_FOUND",
            message="Schedule block not found for this branch.",
        )
    await session.delete(block)
    await record_audit_log(
        session,
        actor_user_id=principal.user.id,
        actor_role=principal.primary_role,
        action="SCHEDULE_BLOCK_DELETED",
        resource_type="schedule_block",
        resource_id=str(block_id),
        branch_id=branch_id,
        request_id=principal.request_id,
        ip_address=principal.ip_address,
    )
    await session.commit()
    return {"deleted": True, "block_id": str(block_id)}


@router.post("/branches/{branch_id}/resources", status_code=status.HTTP_201_CREATED)
async def create_branch_resource(
    branch_id: uuid.UUID,
    payload: CreateResourceRequest,
    principal: PartnerPrincipalDep,
    session: DbSessionDep,
) -> dict[str, Any]:
    """Add a chair or station resource to an authorized branch."""
    await assert_branch_access(session, principal, branch_id)
    resource = Resource(
        branch_id=branch_id,
        name=payload.name.strip(),
        resource_type=payload.resource_type.value,
        is_active=payload.is_active,
    )
    session.add(resource)
    await session.flush()
    await record_audit_log(
        session,
        actor_user_id=principal.user.id,
        actor_role=principal.primary_role,
        action="RESOURCE_CREATED",
        resource_type="resource",
        resource_id=str(resource.id),
        branch_id=branch_id,
        after_state={"name": resource.name, "resource_type": resource.resource_type},
        request_id=principal.request_id,
        ip_address=principal.ip_address,
    )
    await session.commit()
    return {
        "id": str(resource.id),
        "branch_id": str(resource.branch_id),
        "name": resource.name,
        "resource_type": resource.resource_type,
        "is_active": resource.is_active,
    }


@router.patch("/branches/{branch_id}/resources/{resource_id}")
async def update_branch_resource(
    branch_id: uuid.UUID,
    resource_id: uuid.UUID,
    payload: UpdateResourceRequest,
    principal: PartnerPrincipalDep,
    session: DbSessionDep,
) -> dict[str, Any]:
    """Update chair name, type, or active state."""
    await assert_branch_access(session, principal, branch_id)
    resource = await session.scalar(
        select(Resource).where(Resource.id == resource_id, Resource.branch_id == branch_id)
    )
    if resource is None:
        raise ChairAPIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="RESOURCE_NOT_FOUND",
            message="Branch chair resource not found.",
        )
    if payload.name is not None:
        resource.name = payload.name.strip()
    if payload.resource_type is not None:
        resource.resource_type = payload.resource_type.value
    if payload.is_active is not None:
        resource.is_active = payload.is_active

    await record_audit_log(
        session,
        actor_user_id=principal.user.id,
        actor_role=principal.primary_role,
        action="RESOURCE_UPDATED",
        resource_type="resource",
        resource_id=str(resource.id),
        branch_id=branch_id,
        after_state={"name": resource.name, "is_active": resource.is_active},
        request_id=principal.request_id,
        ip_address=principal.ip_address,
    )
    await session.commit()
    return {
        "id": str(resource.id),
        "branch_id": str(resource.branch_id),
        "name": resource.name,
        "resource_type": resource.resource_type,
        "is_active": resource.is_active,
    }


@router.post("/branches/{branch_id}/documents", status_code=status.HTTP_201_CREATED)
async def upload_branch_document(
    branch_id: uuid.UUID,
    payload: UploadDocumentRequest,
    principal: PartnerPrincipalDep,
    session: DbSessionDep,
    storage: StorageProviderDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    """Validate and privately store a KYC verification document, returning a signed preview URL."""
    branch = await assert_branch_access(
        session, principal, branch_id, allowed_roles=(UserRole.PARTNER_OWNER,)
    )
    doc = await upload_branch_kyc_document(
        session,
        principal=principal,
        branch=branch,
        storage=storage,
        max_bytes=settings.max_upload_size_bytes,
        document_type=payload.document_type,
        mime_type=payload.mime_type.strip().lower(),
        content_base64=payload.content_base64,
    )
    return serialize_document_row(doc, storage=storage)

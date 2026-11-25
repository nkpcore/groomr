"""Partner onboarding, branch catalog/staff/shift setup, and private KYC upload services."""

from __future__ import annotations

import base64
import binascii
import re
import uuid
from datetime import UTC, datetime, time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import status
from geoalchemy2 import Geometry
from sqlalchemy import cast, delete, desc, func, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from chair_api.adapters.base import StorageProvider
from chair_api.core.errors import ChairAPIError
from chair_api.db.models import (
    Branch,
    BranchService,
    Inspection,
    Resource,
    Salon,
    SalonDocument,
    ScheduleBlock,
    Service,
    Staff,
    StaffService,
    StaffShift,
    UserRoleAssignment,
)
from chair_api.domain.enums import (
    BranchStatus,
    BranchVerificationStatus,
    DocumentType,
    InspectionOutcome,
    ResourceType,
    SalonStatus,
    ScheduleBlockType,
    StaffStatus,
    UserRole,
)
from chair_api.security.rbac import AuthPrincipal
from chair_api.services.audit import record_audit_log
from chair_api.services.availability import DEFAULT_TIMEZONE

WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

DEFAULT_OPERATING_HOURS: dict[str, dict[str, str] | None] = {
    "mon": {"open": "09:30", "close": "21:30"},
    "tue": {"open": "09:30", "close": "21:30"},
    "wed": {"open": "09:30", "close": "21:30"},
    "thu": {"open": "09:30", "close": "21:30"},
    "fri": {"open": "09:30", "close": "21:30"},
    "sat": {"open": "09:00", "close": "22:00"},
    "sun": {"open": "10:00", "close": "21:00"},
}

MIME_TO_EXTENSION: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "application/pdf": "pdf",
}

_HHMM_RE = re.compile(r"^\d{2}:\d{2}$")
_SLUG_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def parse_hhmm(raw: str, *, field_name: str = "time") -> time:
    """Validate and parse strict HH:MM 24-hour local time."""
    if not _HHMM_RE.match(raw):
        raise ChairAPIError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="INVALID_TIME_FORMAT",
            message=f"{field_name} must follow HH:MM 24-hour format.",
        )
    hour_str, minute_str = raw.split(":", maxsplit=1)
    hour, minute = int(hour_str), int(minute_str)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ChairAPIError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="INVALID_TIME_RANGE",
            message=f"{field_name} has invalid hour or minute values.",
        )
    return time(hour=hour, minute=minute)


def validate_operating_hours(
    hours: dict[str, dict[str, str] | None] | None,
) -> dict[str, dict[str, str] | None]:
    """Normalize and validate operating hours across all 7 weekday keys."""
    if hours is None:
        return {k: (dict(v) if v else None) for k, v in DEFAULT_OPERATING_HOURS.items()}
    unknown_keys = [k for k in hours if k not in WEEKDAY_KEYS]
    if unknown_keys:
        raise ChairAPIError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="INVALID_OPERATING_HOURS_KEY",
            message=f"Unknown weekday keys: {', '.join(unknown_keys)}.",
        )
    normalized: dict[str, dict[str, str] | None] = {}
    for key in WEEKDAY_KEYS:
        day_val = hours.get(key)
        if day_val is None:
            normalized[key] = None
            continue
        open_str = str(day_val.get("open", "")).strip()
        close_str = str(day_val.get("close", "")).strip()
        open_t = parse_hhmm(open_str, field_name=f"operating_hours.{key}.open")
        close_t = parse_hhmm(close_str, field_name=f"operating_hours.{key}.close")
        if close_t <= open_t:
            raise ChairAPIError(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                code="INVALID_OPERATING_HOURS",
                message=f"Closing time must be after opening time for {key}.",
            )
        normalized[key] = {"open": open_str, "close": close_str}
    return normalized


async def _insert_branch_with_unique_slug(
    session: AsyncSession,
    *,
    salon_id: uuid.UUID,
    name: str,
    city: str,
    address_line1: str,
    address_line2: str | None,
    state: str,
    pincode: str,
    location_wkt: str,
    operating_hours: dict[str, dict[str, str] | None],
) -> Branch:
    """Insert a branch while retrying slug suffix collisions via nested savepoints."""
    base_slug = await _build_unique_slug(session, name, city)
    for attempt in range(4):
        slug = base_slug if attempt == 0 else f"{base_slug[:150]}-{uuid.uuid4().hex[:6]}"
        branch = Branch(
            salon_id=salon_id,
            name=name.strip(),
            slug=slug,
            address_line1=address_line1.strip(),
            address_line2=(address_line2 or "").strip() or None,
            city=city.strip(),
            state=state.strip(),
            pincode=pincode.strip(),
            location=location_wkt,
            operating_hours_json=operating_hours,
            status=BranchStatus.DRAFT.value,
            verification_status=BranchVerificationStatus.UNVERIFIED.value,
        )
        try:
            async with session.begin_nested():
                session.add(branch)
                await session.flush()
            return branch
        except IntegrityError:
            if attempt == 3:
                raise
    raise RuntimeError("Unreachable branch slug retry exit.")


async def get_latest_completed_inspection(
    session: AsyncSession, branch_id: uuid.UUID
) -> Inspection | None:
    """Fetch the most recent completed inspection, ignoring SCHEDULED rows."""
    return await session.scalar(
        select(Inspection)
        .where(
            Inspection.branch_id == branch_id,
            Inspection.overall_outcome != InspectionOutcome.SCHEDULED.value,
        )
        .order_by(desc(Inspection.completed_at).nulls_last(), desc(Inspection.created_at))
        .limit(1)
    )


async def _build_unique_slug(session: AsyncSession, name: str, city: str) -> str:
    base = _SLUG_NON_ALNUM_RE.sub("-", f"{name}-{city}".lower()).strip("-") or "chair-branch"
    base = base[:150]
    exists = await session.scalar(select(Branch.id).where(Branch.slug == base))
    if exists is None:
        return base
    for _ in range(10):
        candidate = f"{base}-{uuid.uuid4().hex[:6]}"
        taken = await session.scalar(select(Branch.id).where(Branch.slug == candidate))
        if taken is None:
            return candidate
    return f"{base}-{uuid.uuid4().hex[:10]}"


def _point_wkt(lat: float, lng: float) -> str:
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
        raise ChairAPIError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="INVALID_COORDINATES",
            message="Latitude must be [-90, 90] and longitude must be [-180, 180].",
        )
    return f"SRID=4326;POINT({lng:.6f} {lat:.6f})"


async def _create_initial_chairs(
    session: AsyncSession, *, branch_id: uuid.UUID, count: int
) -> None:
    for idx in range(1, count + 1):
        session.add(
            Resource(
                branch_id=branch_id,
                name=f"Chair {idx}",
                resource_type=ResourceType.BARBER_CHAIR.value,
                is_active=True,
            )
        )


async def onboard_salon_with_branch(
    session: AsyncSession,
    *,
    principal: AuthPrincipal,
    legal_name: str,
    brand_name: str,
    gstin: str | None,
    pan_masked: str | None,
    branch_name: str,
    address_line1: str,
    address_line2: str | None,
    city: str,
    state: str,
    pincode: str,
    lat: float,
    lng: float,
    operating_hours: dict[str, dict[str, str] | None] | None,
    initial_chair_count: int,
) -> tuple[Salon, Branch]:
    """Register a new salon + initial PostGIS branch and grant scoped PARTNER_OWNER role."""
    normalized_hours = validate_operating_hours(operating_hours)
    location_wkt = _point_wkt(lat, lng)

    salon = Salon(
        owner_user_id=principal.user.id,
        legal_name=legal_name.strip(),
        brand_name=brand_name.strip(),
        gstin=(gstin or "").strip() or None,
        pan_masked=(pan_masked or "").strip() or None,
        status=SalonStatus.DRAFT.value,
        verification_badge_status="UNVERIFIED",
    )
    session.add(salon)
    await session.flush()

    branch = await _insert_branch_with_unique_slug(
        session,
        salon_id=salon.id,
        name=branch_name,
        city=city,
        address_line1=address_line1,
        address_line2=address_line2,
        state=state,
        pincode=pincode,
        location_wkt=location_wkt,
        operating_hours=normalized_hours,
    )

    if initial_chair_count > 0:
        await _create_initial_chairs(session, branch_id=branch.id, count=initial_chair_count)

    existing_role = await session.scalar(
        select(UserRoleAssignment).where(
            UserRoleAssignment.user_id == principal.user.id,
            UserRoleAssignment.role == UserRole.PARTNER_OWNER.value,
            UserRoleAssignment.salon_id == salon.id,
            UserRoleAssignment.branch_id.is_(None),
        )
    )
    if existing_role is None:
        session.add(
            UserRoleAssignment(
                user_id=principal.user.id,
                role=UserRole.PARTNER_OWNER.value,
                salon_id=salon.id,
                branch_id=None,
                granted_by=principal.user.id,
            )
        )

    await record_audit_log(
        session,
        actor_user_id=principal.user.id,
        actor_role=principal.primary_role,
        action="SALON_ONBOARDED",
        resource_type="salon",
        resource_id=str(salon.id),
        branch_id=branch.id,
        after_state={"brand_name": salon.brand_name, "branch_slug": branch.slug},
        request_id=principal.request_id,
        ip_address=principal.ip_address,
    )
    await session.commit()
    return salon, branch


async def create_branch_for_salon(
    session: AsyncSession,
    *,
    principal: AuthPrincipal,
    salon: Salon,
    branch_name: str,
    address_line1: str,
    address_line2: str | None,
    city: str,
    state: str,
    pincode: str,
    lat: float,
    lng: float,
    operating_hours: dict[str, dict[str, str] | None] | None,
    initial_chair_count: int,
) -> Branch:
    """Create an additional draft branch under an owner's existing salon."""
    normalized_hours = validate_operating_hours(operating_hours)
    location_wkt = _point_wkt(lat, lng)

    branch = await _insert_branch_with_unique_slug(
        session,
        salon_id=salon.id,
        name=branch_name,
        city=city,
        address_line1=address_line1,
        address_line2=address_line2,
        state=state,
        pincode=pincode,
        location_wkt=location_wkt,
        operating_hours=normalized_hours,
    )

    if initial_chair_count > 0:
        await _create_initial_chairs(session, branch_id=branch.id, count=initial_chair_count)

    await record_audit_log(
        session,
        actor_user_id=principal.user.id,
        actor_role=principal.primary_role,
        action="BRANCH_CREATED",
        resource_type="branch",
        resource_id=str(branch.id),
        branch_id=branch.id,
        after_state={"name": branch.name, "slug": branch.slug, "city": branch.city},
        request_id=principal.request_id,
        ip_address=principal.ip_address,
    )
    await session.commit()
    return branch


def serialize_document_row(doc: SalonDocument, *, storage: StorageProvider) -> dict[str, Any]:
    """Serialize a private KYC document with a short-lived signed retrieval URL."""
    return {
        "id": str(doc.id),
        "salon_id": str(doc.salon_id),
        "branch_id": str(doc.branch_id) if doc.branch_id else None,
        "document_type": doc.document_type,
        "mime_type": doc.mime_type,
        "size_bytes": doc.size_bytes,
        "sha256_hex": doc.sha256_hex,
        "review_status": doc.review_status,
        "rejection_reason": doc.rejection_reason,
        "reviewed_at": doc.reviewed_at.isoformat() if doc.reviewed_at else None,
        "created_at": doc.created_at.isoformat(),
        "signed_url": storage.create_signed_url(object_key=doc.storage_key, ttl_seconds=600),
    }


def serialize_inspection_row(inspection: Inspection) -> dict[str, Any]:
    return {
        "id": str(inspection.id),
        "branch_id": str(inspection.branch_id),
        "overall_outcome": inspection.overall_outcome,
        "numerical_score": inspection.numerical_score,
        "single_use_blades_ok": inspection.single_use_blades_ok,
        "sharps_disposal_ok": inspection.sharps_disposal_ok,
        "instrument_disinfection_ok": inspection.instrument_disinfection_ok,
        "fresh_towels_ok": inspection.fresh_towels_ok,
        "corrective_action_notes": inspection.corrective_action_notes,
        "reinspection_due_at": (
            inspection.reinspection_due_at.isoformat() if inspection.reinspection_due_at else None
        ),
        "completed_at": inspection.completed_at.isoformat() if inspection.completed_at else None,
    }


async def load_branch_setup_state(
    session: AsyncSession,
    *,
    branch_id: uuid.UUID,
    storage: StorageProvider,
    principal: AuthPrincipal | None = None,
) -> dict[str, Any]:
    """Load complete setup & KYC summary for an authorized partner branch."""
    row = (
        await session.execute(
            select(
                Branch,
                Salon,
                func.ST_Y(cast(Branch.location, Geometry)).label("lat"),
                func.ST_X(cast(Branch.location, Geometry)).label("lng"),
            )
            .join(Salon, Salon.id == Branch.salon_id)
            .where(Branch.id == branch_id)
        )
    ).first()
    assert row is not None
    branch, salon, lat_val, lng_val = row

    catalog_services = list(
        await session.scalars(
            select(Service).where(Service.is_active.is_(True)).order_by(Service.name_en.asc())
        )
    )
    branch_service_rows = (
        await session.execute(
            select(BranchService, Service.code, Service.category)
            .join(Service, Service.id == BranchService.service_id)
            .where(BranchService.branch_id == branch_id)
            .order_by(BranchService.display_name_en.asc())
        )
    ).all()

    staff_rows = list(
        await session.scalars(
            select(Staff).where(Staff.branch_id == branch_id).order_by(Staff.display_name.asc())
        )
    )
    staff_ids = [s.id for s in staff_rows]
    quals_by_staff: dict[uuid.UUID, list[str]] = {sid: [] for sid in staff_ids}
    shifts_by_staff: dict[uuid.UUID, list[dict[str, Any]]] = {sid: [] for sid in staff_ids}

    if staff_ids:
        qual_rows = list(
            await session.scalars(
                select(StaffService).where(
                    StaffService.staff_id.in_(staff_ids), StaffService.is_active.is_(True)
                )
            )
        )
        for q in qual_rows:
            quals_by_staff.setdefault(q.staff_id, []).append(str(q.branch_service_id))

        shift_rows = list(
            await session.scalars(
                select(StaffShift)
                .where(StaffShift.staff_id.in_(staff_ids), StaffShift.is_active.is_(True))
                .order_by(StaffShift.weekday.asc(), StaffShift.start_time_local.asc())
            )
        )
        for sh in shift_rows:
            shifts_by_staff.setdefault(sh.staff_id, []).append(
                {
                    "id": str(sh.id),
                    "weekday": sh.weekday,
                    "start_time": sh.start_time_local.strftime("%H:%M"),
                    "end_time": sh.end_time_local.strftime("%H:%M"),
                    "timezone": sh.timezone,
                }
            )

    block_rows = list(
        await session.scalars(
            select(ScheduleBlock)
            .where(ScheduleBlock.branch_id == branch_id)
            .order_by(desc(ScheduleBlock.created_at))
            .limit(40)
        )
    )
    resource_rows = list(
        await session.scalars(
            select(Resource).where(Resource.branch_id == branch_id).order_by(Resource.name.asc())
        )
    )
    can_view_salon_docs = (
        principal is None
        or principal.can_access_salon(salon.id, salon_owner_user_id=salon.owner_user_id)
    )
    doc_filter = (
        (SalonDocument.branch_id == branch_id) | (SalonDocument.branch_id.is_(None))
        if can_view_salon_docs
        else (SalonDocument.branch_id == branch_id)
    )
    doc_rows = list(
        await session.scalars(
            select(SalonDocument)
            .where(SalonDocument.salon_id == salon.id, doc_filter)
            .order_by(desc(SalonDocument.created_at))
        )
    )
    latest_insp = await get_latest_completed_inspection(session, branch_id)

    return {
        "branch": {
            "id": str(branch.id),
            "salon_id": str(salon.id),
            "salon_brand_name": salon.brand_name,
            "salon_status": salon.status,
            "name": branch.name,
            "slug": branch.slug,
            "address_line1": branch.address_line1,
            "address_line2": branch.address_line2,
            "city": branch.city,
            "state": branch.state,
            "pincode": branch.pincode,
            "lat": float(lat_val),
            "lng": float(lng_val),
            "operating_hours_json": branch.operating_hours_json,
            "online_booking_paused": branch.online_booking_paused,
            "is_featured": branch.is_featured,
            "featured_disclosure_label": branch.featured_disclosure_label,
            "status": branch.status,
            "verification_status": branch.verification_status,
        },
        "catalog_services": [
            {
                "id": str(svc.id),
                "code": svc.code,
                "name_en": svc.name_en,
                "name_hi": svc.name_hi,
                "category": svc.category,
                "default_duration_minutes": svc.default_duration_minutes,
            }
            for svc in catalog_services
        ],
        "branch_services": [
            {
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
            for bs, code, category in branch_service_rows
        ],
        "staff": [
            {
                "id": str(st.id),
                "branch_id": str(st.branch_id),
                "display_name": st.display_name,
                "bio": st.bio,
                "specializations": list(st.specializations_json or []),
                "is_verified_staff": st.is_verified_staff,
                "is_accepting_bookings": st.is_accepting_bookings,
                "status": st.status,
                "qualified_branch_service_ids": quals_by_staff.get(st.id, []),
                "shifts": shifts_by_staff.get(st.id, []),
            }
            for st in staff_rows
        ],
        "schedule_blocks": [
            {
                "id": str(bl.id),
                "branch_id": str(bl.branch_id),
                "staff_id": str(bl.staff_id) if bl.staff_id else None,
                "block_type": bl.block_type,
                "start_at": (
                    bl.blocked_range.lower.astimezone(UTC).isoformat()
                    if bl.blocked_range.lower is not None
                    else ""
                ),
                "end_at": (
                    bl.blocked_range.upper.astimezone(UTC).isoformat()
                    if bl.blocked_range.upper is not None
                    else ""
                ),
                "reason": bl.reason,
            }
            for bl in block_rows
        ],
        "resources": [
            {
                "id": str(r.id),
                "branch_id": str(r.branch_id),
                "name": r.name,
                "resource_type": r.resource_type,
                "is_active": r.is_active,
            }
            for r in resource_rows
        ],
        "documents": [serialize_document_row(doc, storage=storage) for doc in doc_rows],
        "latest_inspection": (
            serialize_inspection_row(latest_insp) if latest_insp is not None else None
        ),
    }


async def upsert_staff_qualifications_and_shifts(
    session: AsyncSession,
    *,
    branch_id: uuid.UUID,
    staff: Staff,
    qualified_branch_service_ids: list[uuid.UUID] | None,
    shifts: list[dict[str, Any]] | None,
) -> None:
    """Validate and apply branch-scoped service qualifications and weekly shifts for staff."""
    if qualified_branch_service_ids is not None:
        unique_ids = list(dict.fromkeys(qualified_branch_service_ids))
        if unique_ids:
            valid_count = int(
                await session.scalar(
                    select(func.count(BranchService.id)).where(
                        BranchService.branch_id == branch_id,
                        BranchService.id.in_(unique_ids),
                    )
                )
                or 0
            )
            if valid_count != len(unique_ids):
                raise ChairAPIError(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    code="INVALID_BRANCH_SERVICE_REFERENCE",
                    message="All qualified services must belong to this branch.",
                )
        await session.execute(delete(StaffService).where(StaffService.staff_id == staff.id))
        for bs_id in unique_ids:
            session.add(
                StaffService(staff_id=staff.id, branch_service_id=bs_id, is_active=True)
            )

    if shifts is not None:
        await session.execute(delete(StaffShift).where(StaffShift.staff_id == staff.id))
        for item in shifts:
            weekday = int(item["weekday"])
            if not 0 <= weekday <= 6:
                raise ChairAPIError(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    code="INVALID_WEEKDAY",
                    message="Weekday must be between 0 (Monday) and 6 (Sunday).",
                )
            start_t = parse_hhmm(str(item["start_time"]), field_name="shifts.start_time")
            end_t = parse_hhmm(str(item["end_time"]), field_name="shifts.end_time")
            if end_t <= start_t:
                raise ChairAPIError(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    code="INVALID_SHIFT_WINDOW",
                    message="Shift end_time must be after start_time.",
                )
            tz_name = str(item.get("timezone") or DEFAULT_TIMEZONE).strip()
            try:
                ZoneInfo(tz_name)
            except ZoneInfoNotFoundError as exc:
                raise ChairAPIError(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    code="INVALID_TIMEZONE",
                    message=f"Unknown IANA timezone: {tz_name}",
                ) from exc
            session.add(
                StaffShift(
                    staff_id=staff.id,
                    branch_id=branch_id,
                    weekday=weekday,
                    start_time_local=start_t,
                    end_time_local=end_t,
                    timezone=tz_name,
                    is_active=True,
                )
            )


async def upload_branch_kyc_document(
    session: AsyncSession,
    *,
    principal: AuthPrincipal,
    branch: Branch,
    storage: StorageProvider,
    max_bytes: int,
    document_type: DocumentType,
    mime_type: str,
    content_base64: str,
) -> SalonDocument:
    """Validate base64 KYC document magic bytes/size, store privately, and log audit entry."""
    cleaned = "".join(content_base64.split())
    try:
        raw_bytes = base64.b64decode(cleaned, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ChairAPIError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="INVALID_BASE64_CONTENT",
            message="Uploaded document content is not valid base64.",
        ) from exc

    try:
        sha256_hex = storage.validate_upload(
            content=raw_bytes,
            declared_mime=mime_type,
            max_bytes=max_bytes,
        )
    except ValueError as exc:
        raise ChairAPIError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="INVALID_UPLOAD",
            message=str(exc),
        ) from exc

    ext = MIME_TO_EXTENSION[mime_type]
    object_key = f"kyc/{branch.salon_id}/{branch.id}/{uuid.uuid4().hex}.{ext}"

    doc = SalonDocument(
        salon_id=branch.salon_id,
        branch_id=branch.id,
        document_type=document_type.value,
        storage_key=object_key,
        mime_type=mime_type,
        size_bytes=len(raw_bytes),
        sha256_hex=sha256_hex,
        review_status="PENDING",
    )
    session.add(doc)
    await session.flush()

    if branch.verification_status == BranchVerificationStatus.UNVERIFIED.value:
        branch.verification_status = BranchVerificationStatus.PENDING.value
    salon = await session.scalar(select(Salon).where(Salon.id == branch.salon_id))
    if salon is not None:
        if salon.status == SalonStatus.DRAFT.value:
            salon.status = SalonStatus.PENDING_REVIEW.value
        if salon.verification_badge_status == "UNVERIFIED":
            salon.verification_badge_status = "PENDING"

    await record_audit_log(
        session,
        actor_user_id=principal.user.id,
        actor_role=principal.primary_role,
        action="KYC_DOCUMENT_UPLOADED",
        resource_type="salon_document",
        resource_id=str(doc.id),
        branch_id=branch.id,
        after_state={
            "document_type": doc.document_type,
            "mime_type": doc.mime_type,
            "size_bytes": doc.size_bytes,
            "sha256_hex": doc.sha256_hex,
        },
        request_id=principal.request_id,
        ip_address=principal.ip_address,
    )
    storage.store_object(object_key=object_key, content=raw_bytes)
    try:
        await session.commit()
    except Exception:
        storage.delete_object(object_key=object_key)
        raise
    return doc


async def create_branch_schedule_block(
    session: AsyncSession,
    *,
    principal: AuthPrincipal,
    branch_id: uuid.UUID,
    staff_id: uuid.UUID | None,
    block_type: ScheduleBlockType,
    start_at: datetime,
    end_at: datetime,
    reason: str | None,
) -> ScheduleBlock:
    if start_at.tzinfo is None or end_at.tzinfo is None:
        raise ChairAPIError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="TIMEZONE_REQUIRED",
            message="Schedule block timestamps must include timezone offset.",
        )
    start_utc = start_at.astimezone(UTC)
    end_utc = end_at.astimezone(UTC)
    if end_utc <= start_utc:
        raise ChairAPIError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="INVALID_BLOCK_RANGE",
            message="Schedule block end_at must be after start_at.",
        )
    if staff_id is not None:
        staff_row = await session.scalar(
            select(Staff).where(Staff.id == staff_id, Staff.branch_id == branch_id)
        )
        if staff_row is None:
            raise ChairAPIError(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                code="INVALID_STAFF_FOR_BRANCH",
                message="Selected staff member does not belong to this branch.",
            )
    block = ScheduleBlock(
        branch_id=branch_id,
        staff_id=staff_id,
        block_type=block_type.value,
        blocked_range=Range(start_utc, end_utc, bounds="[)"),
        reason=(reason or "").strip() or None,
    )
    session.add(block)
    await session.flush()
    await record_audit_log(
        session,
        actor_user_id=principal.user.id,
        actor_role=principal.primary_role,
        action="SCHEDULE_BLOCK_CREATED",
        resource_type="schedule_block",
        resource_id=str(block.id),
        branch_id=branch_id,
        after_state={
            "block_type": block.block_type,
            "start_at": start_utc.isoformat(),
            "end_at": end_utc.isoformat(),
        },
        request_id=principal.request_id,
        ip_address=principal.ip_address,
    )
    await session.commit()
    return block


def validate_staff_status(status_val: StaffStatus) -> str:
    return status_val.value

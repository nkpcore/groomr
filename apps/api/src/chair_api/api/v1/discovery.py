"""Public PostGIS salon discovery, branch details, and real-time slot availability endpoints."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, status
from geoalchemy2 import Geography, Geometry
from pydantic import BaseModel
from sqlalchemy import Select, cast, desc, func, or_, select

from chair_api.api.deps import DbSessionDep, SettingsDep
from chair_api.core.errors import ChairAPIError
from chair_api.db.models import (
    Branch,
    BranchService,
    Inspection,
    Resource,
    Review,
    Salon,
    Service,
    Staff,
    StaffService,
)
from chair_api.domain.enums import BranchVerificationStatus, ServiceCategory
from chair_api.services.availability import (
    DEFAULT_TIMEZONE,
    NextSlotProbe,
    ServiceSpec,
    is_branch_open_now,
    load_branch_availability_from_db,
    load_branches_next_available_slots,
)

router = APIRouter()

VERIFICATION_DISCLAIMER = (
    "CHAIR VERIFIED is an independent platform verification badge based on document checks "
    "and physical hygiene inspection; not government licensing."
)


def _escape_like(raw: str) -> str:
    return raw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class BranchServicePreview(BaseModel):
    id: uuid.UUID
    code: str
    category: ServiceCategory
    display_name_en: str
    display_name_hi: str
    description: str | None
    price_paise: int
    duration_minutes: int
    buffer_before_minutes: int
    buffer_after_minutes: int


class BranchDiscoveryItem(BaseModel):
    id: uuid.UUID
    salon_id: uuid.UUID
    brand_name: str
    name: str
    slug: str
    address_line1: str
    city: str
    state: str
    pincode: str
    lat: float
    lng: float
    distance_meters: int | None
    verification_status: BranchVerificationStatus
    is_featured: bool
    featured_disclosure_label: str | None
    online_booking_paused: bool
    is_open_now: bool
    starting_price_paise: int | None
    avg_rating: float | None
    review_count: int
    categories: list[ServiceCategory]
    service_previews: list[BranchServicePreview]
    next_available_slot_at: datetime | None


class BranchListResponse(BaseModel):
    items: list[BranchDiscoveryItem]
    total_count: int
    verification_badge_disclaimer: str


class PublicStaffItem(BaseModel):
    id: uuid.UUID
    display_name: str
    bio: str | None
    specializations: list[str]
    is_verified_staff: bool
    is_accepting_bookings: bool
    qualified_branch_service_ids: list[uuid.UUID]


class PublicReviewItem(BaseModel):
    id: uuid.UUID
    rating: int
    hygiene_rating: int
    comment: str | None
    created_at: datetime


class RatingSummary(BaseModel):
    avg_rating: float | None
    avg_hygiene_rating: float | None
    review_count: int
    recent_reviews: list[PublicReviewItem]


class InspectionSummary(BaseModel):
    overall_outcome: str
    completed_at: datetime | None
    numerical_score: int | None


class BranchDetailResponse(BaseModel):
    id: uuid.UUID
    salon_id: uuid.UUID
    brand_name: str
    name: str
    slug: str
    address_line1: str
    address_line2: str | None
    city: str
    state: str
    pincode: str
    lat: float
    lng: float
    operating_hours_json: dict[str, Any]
    verification_status: BranchVerificationStatus
    verification_badge_disclaimer: str
    is_featured: bool
    featured_disclosure_label: str | None
    online_booking_paused: bool
    is_open_now: bool
    chair_count: int
    services: list[BranchServicePreview]
    staff: list[PublicStaffItem]
    rating_summary: RatingSummary
    latest_inspection: InspectionSummary | None


class SlotStaffOptionOut(BaseModel):
    staff_id: uuid.UUID
    display_name: str
    is_verified_staff: bool
    duration_minutes: int
    end_at: datetime


class AvailableSlotOut(BaseModel):
    start_at: datetime
    end_at: datetime
    duration_minutes: int
    available_staff: list[SlotStaffOptionOut]
    available_chair_count: int


class AvailabilityResponse(BaseModel):
    branch_id: uuid.UUID
    date: date
    timezone: str
    online_booking_paused: bool
    is_branch_closed: bool
    slots: list[AvailableSlotOut]


@router.get("", response_model=BranchListResponse)
async def list_branches(
    session: DbSessionDep,
    settings: SettingsDep,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lng: Annotated[float | None, Query(ge=-180, le=180)] = None,
    radius_meters: Annotated[int | None, Query(ge=500, le=100_000)] = None,
    city: Annotated[str | None, Query(max_length=80)] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    category: ServiceCategory | None = None,
    max_price_paise: Annotated[int | None, Query(ge=0)] = None,
    verified_only: bool = False,
    open_now: bool = False,
    min_rating: Annotated[float | None, Query(ge=1.0, le=5.0)] = None,
    sort: Literal["distance", "price_asc", "rating", "featured"] = "distance",
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BranchListResponse:
    """Search active salons by PostGIS radius, price, rating, and real availability."""
    if (lat is None) != (lng is None):
        raise ChairAPIError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="INVALID_COORDINATES",
            message="Both lat and lng must be provided together.",
        )

    effective_radius = min(
        radius_meters if radius_meters is not None else settings.default_search_radius_meters,
        settings.max_search_radius_meters,
    )

    lat_expr = func.ST_Y(cast(Branch.location, Geometry)).label("lat")
    lng_expr = func.ST_X(cast(Branch.location, Geometry)).label("lng")

    if lat is not None and lng is not None:
        user_geog = cast(func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326), Geography)
        dist_expr: Any = func.ST_Distance(Branch.location, user_geog).label("distance_meters")
    else:
        dist_expr = None

    price_subq = (
        select(
            BranchService.branch_id.label("branch_id"),
            func.min(BranchService.price_paise).label("starting_price_paise"),
        )
        .join(Service, Service.id == BranchService.service_id)
        .where(
            BranchService.is_active.is_(True),
            Service.is_active.is_(True),
            *([] if category is None else [Service.category == category.value]),
        )
        .group_by(BranchService.branch_id)
        .subquery()
    )

    review_subq = (
        select(
            Review.branch_id.label("branch_id"),
            func.avg(Review.rating).label("avg_rating"),
            func.count(Review.id).label("review_count"),
        )
        .where(Review.is_published.is_(True))
        .group_by(Review.branch_id)
        .subquery()
    )

    stmt: Select[Any] = (
        select(
            Branch,
            Salon.brand_name,
            lat_expr,
            lng_expr,
            price_subq.c.starting_price_paise,
            review_subq.c.avg_rating,
            func.coalesce(review_subq.c.review_count, 0).label("review_count"),
            *([] if dist_expr is None else [dist_expr]),
        )
        .join(Salon, Salon.id == Branch.salon_id)
        .outerjoin(price_subq, price_subq.c.branch_id == Branch.id)
        .outerjoin(review_subq, review_subq.c.branch_id == Branch.id)
        .where(
            Branch.status == "ACTIVE",
            Salon.status == "ACTIVE",
            Branch.verification_status != BranchVerificationStatus.SUSPENDED.value,
        )
    )

    if lat is not None and lng is not None:
        user_geog = cast(func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326), Geography)
        stmt = stmt.where(func.ST_DWithin(Branch.location, user_geog, effective_radius))

    if city and city.strip():
        stmt = stmt.where(Branch.city.ilike(_escape_like(city.strip()), escape="\\"))

    if verified_only:
        stmt = stmt.where(
            Branch.verification_status == BranchVerificationStatus.CHAIR_VERIFIED.value
        )

    if category is not None:
        stmt = stmt.where(price_subq.c.starting_price_paise.is_not(None))

    if max_price_paise is not None:
        stmt = stmt.where(price_subq.c.starting_price_paise <= max_price_paise)

    if min_rating is not None:
        stmt = stmt.where(review_subq.c.avg_rating >= min_rating)

    if q and q.strip():
        pattern = f"%{_escape_like(q.strip())}%"
        service_match = (
            select(BranchService.id)
            .join(Service, Service.id == BranchService.service_id)
            .where(
                BranchService.branch_id == Branch.id,
                BranchService.is_active.is_(True),
                Service.is_active.is_(True),
                or_(
                    BranchService.display_name_en.ilike(pattern, escape="\\"),
                    BranchService.display_name_hi.ilike(pattern, escape="\\"),
                ),
            )
            .exists()
        )
        stmt = stmt.where(
            or_(
                Branch.name.ilike(pattern, escape="\\"),
                Branch.address_line1.ilike(pattern, escape="\\"),
                Branch.city.ilike(pattern, escape="\\"),
                Salon.brand_name.ilike(pattern, escape="\\"),
                service_match,
            )
        )

    if open_now:
        stmt = stmt.where(Branch.online_booking_paused.is_(False))

    if sort == "price_asc":
        stmt = stmt.order_by(
            price_subq.c.starting_price_paise.asc().nulls_last(), Branch.name.asc()
        )
    elif sort == "rating":
        stmt = stmt.order_by(review_subq.c.avg_rating.desc().nulls_last(), Branch.name.asc())
    elif sort == "featured":
        if dist_expr is not None:
            stmt = stmt.order_by(Branch.is_featured.desc(), dist_expr.asc(), Branch.name.asc())
        else:
            stmt = stmt.order_by(Branch.is_featured.desc(), Branch.name.asc())
    else:
        if dist_expr is not None:
            stmt = stmt.order_by(dist_expr.asc(), Branch.name.asc())
        else:
            stmt = stmt.order_by(Branch.name.asc())

    now_utc = datetime.now(UTC)

    if not open_now:
        total_count = int(
            await session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
            or 0
        )
        rows = (await session.execute(stmt.offset(offset).limit(limit))).all()
    else:
        # Operating hours vary per weekday JSON; fetch matching SQL candidates and paginate cleanly.
        candidate_rows = (await session.execute(stmt)).all()
        open_rows = [
            row
            for row in candidate_rows
            if is_branch_open_now(row[0].operating_hours_json, now_utc)
        ]
        total_count = len(open_rows)
        rows = open_rows[offset : offset + limit]

    if not rows:
        return BranchListResponse(
            items=[],
            total_count=total_count,
            verification_badge_disclaimer=VERIFICATION_DISCLAIMER,
        )

    page_branch_ids = [row[0].id for row in rows]
    svc_rows = (
        await session.execute(
            select(BranchService, Service)
            .join(Service, Service.id == BranchService.service_id)
            .where(
                BranchService.branch_id.in_(page_branch_ids),
                BranchService.is_active.is_(True),
                Service.is_active.is_(True),
            )
            .order_by(BranchService.price_paise.asc())
        )
    ).all()

    services_by_branch: dict[uuid.UUID, list[BranchServicePreview]] = {}
    for bs, svc in svc_rows:
        services_by_branch.setdefault(bs.branch_id, []).append(
            BranchServicePreview(
                id=bs.id,
                code=svc.code,
                category=ServiceCategory(svc.category),
                display_name_en=bs.display_name_en,
                display_name_hi=bs.display_name_hi,
                description=bs.description,
                price_paise=bs.price_paise,
                duration_minutes=bs.duration_minutes,
                buffer_before_minutes=bs.buffer_before_minutes,
                buffer_after_minutes=bs.buffer_after_minutes,
            )
        )

    probes: list[NextSlotProbe] = []
    items: list[BranchDiscoveryItem] = []

    for row in rows:
        branch = row[0]
        brand_name = str(row[1])
        b_lat = float(row[2])
        b_lng = float(row[3])
        starting_price = int(row[4]) if row[4] is not None else None
        avg_rating = round(float(row[5]), 2) if row[5] is not None else None
        review_count = int(row[6] or 0)
        dist_m = int(round(float(row[7]))) if dist_expr is not None else None

        all_branch_svcs = services_by_branch.get(branch.id, [])
        categories = list(dict.fromkeys(s.category for s in all_branch_svcs))
        disclosure = (
            (branch.featured_disclosure_label or "Sponsored") if branch.is_featured else None
        )

        if not branch.online_booking_paused and all_branch_svcs:
            # Resolve from FULL branch services list so categories past index 4 work cleanly
            probe_service = next(
                (s for s in all_branch_svcs if category is None or s.category == category),
                all_branch_svcs[0],
            )
            probes.append(
                NextSlotProbe(
                    branch=branch,
                    service_id=probe_service.id,
                    service_spec=ServiceSpec(
                        branch_service_id=probe_service.id,
                        duration_minutes=probe_service.duration_minutes,
                        buffer_before_minutes=probe_service.buffer_before_minutes,
                        buffer_after_minutes=probe_service.buffer_after_minutes,
                    ),
                )
            )

        items.append(
            BranchDiscoveryItem(
                id=branch.id,
                salon_id=branch.salon_id,
                brand_name=brand_name,
                name=branch.name,
                slug=branch.slug,
                address_line1=branch.address_line1,
                city=branch.city,
                state=branch.state,
                pincode=branch.pincode,
                lat=b_lat,
                lng=b_lng,
                distance_meters=dist_m,
                verification_status=BranchVerificationStatus(branch.verification_status),
                is_featured=branch.is_featured,
                featured_disclosure_label=disclosure,
                online_booking_paused=branch.online_booking_paused,
                is_open_now=is_branch_open_now(branch.operating_hours_json, now_utc),
                starting_price_paise=starting_price,
                avg_rating=avg_rating,
                review_count=review_count,
                categories=categories,
                service_previews=all_branch_svcs[:4],
                next_available_slot_at=None,
            )
        )

    next_slots_map = await load_branches_next_available_slots(
        session, probes=probes, now_utc=now_utc
    )
    for item in items:
        item.next_available_slot_at = next_slots_map.get(item.id)

    return BranchListResponse(
        items=items,
        total_count=total_count,
        verification_badge_disclaimer=VERIFICATION_DISCLAIMER,
    )


@router.get("/{branch_id}", response_model=BranchDetailResponse)
async def get_branch_detail(
    branch_id: uuid.UUID,
    session: DbSessionDep,
) -> BranchDetailResponse:
    """Return full public salon branch profile, services, barbers, reviews, and inspection state."""
    row = (
        await session.execute(
            select(
                Branch,
                Salon.brand_name,
                func.ST_Y(cast(Branch.location, Geometry)),
                func.ST_X(cast(Branch.location, Geometry)),
            )
            .join(Salon, Salon.id == Branch.salon_id)
            .where(
                Branch.id == branch_id,
                Branch.status == "ACTIVE",
                Salon.status == "ACTIVE",
                Branch.verification_status != BranchVerificationStatus.SUSPENDED.value,
            )
        )
    ).first()
    if row is None:
        raise ChairAPIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="BRANCH_NOT_FOUND",
            message="Branch does not exist or is not active.",
        )

    branch, brand_name, b_lat, b_lng = row

    svc_rows = (
        await session.execute(
            select(BranchService, Service)
            .join(Service, Service.id == BranchService.service_id)
            .where(
                BranchService.branch_id == branch.id,
                BranchService.is_active.is_(True),
                Service.is_active.is_(True),
            )
            .order_by(BranchService.price_paise.asc())
        )
    ).all()
    services = [
        BranchServicePreview(
            id=bs.id,
            code=svc.code,
            category=ServiceCategory(svc.category),
            display_name_en=bs.display_name_en,
            display_name_hi=bs.display_name_hi,
            description=bs.description,
            price_paise=bs.price_paise,
            duration_minutes=bs.duration_minutes,
            buffer_before_minutes=bs.buffer_before_minutes,
            buffer_after_minutes=bs.buffer_after_minutes,
        )
        for bs, svc in svc_rows
    ]

    staff_rows = list(
        await session.scalars(
            select(Staff).where(Staff.branch_id == branch.id, Staff.status == "ACTIVE")
        )
    )
    staff_ids = [s.id for s in staff_rows]
    qual_rows = (
        list(
            await session.scalars(
                select(StaffService).where(
                    StaffService.staff_id.in_(staff_ids),
                    StaffService.is_active.is_(True),
                )
            )
        )
        if staff_ids
        else []
    )
    qual_map: dict[uuid.UUID, list[uuid.UUID]] = {}
    for q in qual_rows:
        qual_map.setdefault(q.staff_id, []).append(q.branch_service_id)

    staff_items = [
        PublicStaffItem(
            id=s.id,
            display_name=s.display_name,
            bio=s.bio,
            specializations=list(s.specializations_json or []),
            is_verified_staff=s.is_verified_staff,
            is_accepting_bookings=s.is_accepting_bookings,
            qualified_branch_service_ids=qual_map.get(s.id, []),
        )
        for s in staff_rows
    ]

    chair_count = int(
        await session.scalar(
            select(func.count(Resource.id)).where(
                Resource.branch_id == branch.id, Resource.is_active.is_(True)
            )
        )
        or 0
    )

    review_stats = (
        await session.execute(
            select(
                func.avg(Review.rating),
                func.avg(Review.hygiene_rating),
                func.count(Review.id),
            ).where(Review.branch_id == branch.id, Review.is_published.is_(True))
        )
    ).one()
    recent_reviews = list(
        await session.scalars(
            select(Review)
            .where(Review.branch_id == branch.id, Review.is_published.is_(True))
            .order_by(desc(Review.created_at))
            .limit(10)
        )
    )

    latest_insp = await session.scalar(
        select(Inspection)
        .where(
            Inspection.branch_id == branch.id,
            Inspection.overall_outcome != "SCHEDULED",
        )
        .order_by(desc(Inspection.completed_at).nulls_last(), desc(Inspection.created_at))
        .limit(1)
    )

    return BranchDetailResponse(
        id=branch.id,
        salon_id=branch.salon_id,
        brand_name=str(brand_name),
        name=branch.name,
        slug=branch.slug,
        address_line1=branch.address_line1,
        address_line2=branch.address_line2,
        city=branch.city,
        state=branch.state,
        pincode=branch.pincode,
        lat=float(b_lat),
        lng=float(b_lng),
        operating_hours_json=branch.operating_hours_json,
        verification_status=BranchVerificationStatus(branch.verification_status),
        verification_badge_disclaimer=VERIFICATION_DISCLAIMER,
        is_featured=branch.is_featured,
        featured_disclosure_label=(
            (branch.featured_disclosure_label or "Sponsored") if branch.is_featured else None
        ),
        online_booking_paused=branch.online_booking_paused,
        is_open_now=is_branch_open_now(branch.operating_hours_json),
        chair_count=chair_count,
        services=services,
        staff=staff_items,
        rating_summary=RatingSummary(
            avg_rating=round(float(review_stats[0]), 2) if review_stats[0] is not None else None,
            avg_hygiene_rating=(
                round(float(review_stats[1]), 2) if review_stats[1] is not None else None
            ),
            review_count=int(review_stats[2] or 0),
            recent_reviews=[
                PublicReviewItem(
                    id=rev.id,
                    rating=rev.rating,
                    hygiene_rating=rev.hygiene_rating,
                    comment=rev.comment,
                    created_at=rev.created_at,
                )
                for rev in recent_reviews
            ],
        ),
        latest_inspection=(
            InspectionSummary(
                overall_outcome=latest_insp.overall_outcome,
                completed_at=latest_insp.completed_at,
                numerical_score=(
                    None
                    if latest_insp.overall_outcome == "FAILED_CRITICAL"
                    else latest_insp.numerical_score
                ),
            )
            if latest_insp is not None
            else None
        ),
    )


@router.get("/{branch_id}/availability", response_model=AvailabilityResponse)
async def get_branch_availability(
    branch_id: uuid.UUID,
    session: DbSessionDep,
    service_ids: Annotated[list[uuid.UUID], Query(min_length=1, max_length=5)],
    date_value: Annotated[date, Query(alias="date")],
    staff_id: uuid.UUID | None = None,
) -> AvailabilityResponse:
    """Compute real live time slots for a branch, selected services, date, and optional barber."""
    today_ist = datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).date()
    if date_value < today_ist or date_value > today_ist + timedelta(days=30):
        raise ChairAPIError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="INVALID_DATE_RANGE",
            message="Requested date must be between today and 30 days ahead.",
        )

    branch, computed = await load_branch_availability_from_db(
        session,
        branch_id=branch_id,
        service_ids=service_ids,
        target_date=date_value,
        staff_id=staff_id,
    )

    return AvailabilityResponse(
        branch_id=branch.id,
        date=date_value,
        timezone=DEFAULT_TIMEZONE,
        online_booking_paused=computed.online_booking_paused,
        is_branch_closed=computed.is_branch_closed,
        slots=[
            AvailableSlotOut(
                start_at=slot.start_at,
                end_at=slot.end_at,
                duration_minutes=slot.duration_minutes,
                available_staff=[
                    SlotStaffOptionOut(
                        staff_id=st.staff_id,
                        display_name=st.display_name,
                        is_verified_staff=st.is_verified_staff,
                        duration_minutes=st.duration_minutes,
                        end_at=st.end_at,
                    )
                    for st in slot.available_staff
                ],
                available_chair_count=slot.available_chair_count,
            )
            for slot in computed.slots
        ],
    )

"""Admin-only governance, KYC document review, hygiene inspections, and audit log endpoints."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, status
from geoalchemy2 import Geometry
from pydantic import BaseModel, Field
from sqlalchemy import cast, desc, func, select
from sqlalchemy.exc import IntegrityError

from chair_api.api.deps import DbSessionDep, StorageProviderDep
from chair_api.api.v1.discovery import VERIFICATION_DISCLAIMER
from chair_api.core.errors import ChairAPIError
from chair_api.db.models import (
    AuditLog,
    Branch,
    Inspection,
    Salon,
    SalonDocument,
    VerificationCheck,
)
from chair_api.domain.enums import (
    BranchStatus,
    BranchVerificationStatus,
    DocumentReviewStatus,
    DocumentType,
    InspectionOutcome,
    SalonStatus,
    UserRole,
    VerificationCheckStatus,
    VerificationCheckType,
)
from chair_api.domain.hygiene import HygieneChecklistInput, evaluate_inspection
from chair_api.security.rbac import AuthPrincipal, require_roles
from chair_api.services.audit import record_audit_log
from chair_api.services.partner_ops import (
    get_latest_completed_inspection,
    serialize_document_row,
    serialize_inspection_row,
)

router = APIRouter()
AdminPrincipalDep = Annotated[AuthPrincipal, Depends(require_roles(UserRole.ADMIN))]

DOCUMENT_TO_CHECK_TYPE: dict[str, VerificationCheckType] = {
    DocumentType.OWNER_ID.value: VerificationCheckType.IDENTITY,
    DocumentType.BUSINESS_REGISTRATION.value: VerificationCheckType.BUSINESS,
    DocumentType.SHOP_ESTABLISHMENT_LICENSE.value: VerificationCheckType.LOCAL_LICENSE,
    DocumentType.MUNICIPAL_TRADE_LICENSE.value: VerificationCheckType.LOCAL_LICENSE,
    DocumentType.ADDRESS_PROOF.value: VerificationCheckType.ADDRESS,
    DocumentType.BANK_PROOF.value: VerificationCheckType.BANK_PENNY_DROP,
}


class AuditLogItem(BaseModel):
    id: uuid.UUID
    actor_user_id: uuid.UUID | None
    actor_role: str
    action: str
    resource_type: str
    resource_id: str
    branch_id: uuid.UUID | None
    request_id: str | None
    after_state_json: dict[str, Any] | None
    created_at: datetime


class AuditLogListResponse(BaseModel):
    items: list[AuditLogItem]


class ReviewDocumentRequest(BaseModel):
    review_status: Literal["APPROVED", "REJECTED"]
    rejection_reason: str | None = Field(default=None, max_length=500)


class RecordInspectionRequest(BaseModel):
    numerical_score: int = Field(ge=0, le=100)
    single_use_blades_ok: bool
    sharps_disposal_ok: bool
    instrument_disinfection_ok: bool
    fresh_towels_ok: bool
    corrective_action_notes: str | None = Field(default=None, max_length=1500)
    reinspection_due_at: datetime | None = None
    evidence_keys: list[str] = Field(default_factory=list, max_length=20)


class BranchGovernanceRequest(BaseModel):
    status: BranchStatus | None = None
    verification_status: BranchVerificationStatus | None = None
    is_featured: bool | None = None
    featured_disclosure_label: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=500)


@router.get("/audit-logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    _principal: AdminPrincipalDep,
    session: DbSessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> AuditLogListResponse:
    """Return recent append-only security and governance audit log records."""
    rows = list(
        await session.scalars(
            select(AuditLog).order_by(desc(AuditLog.created_at), desc(AuditLog.id)).limit(limit)
        )
    )
    return AuditLogListResponse(
        items=[
            AuditLogItem(
                id=row.id,
                actor_user_id=row.actor_user_id,
                actor_role=row.actor_role,
                action=row.action,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                branch_id=row.branch_id,
                request_id=row.request_id,
                after_state_json=row.after_state_json,
                created_at=row.created_at,
            )
            for row in rows
        ]
    )


@router.get("/verifications")
async def list_admin_verifications(
    _principal: AdminPrincipalDep,
    session: DbSessionDep,
    storage: StorageProviderDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """List paginated branches with submitted private KYC docs, checks, and hygiene history."""
    total_count = int(await session.scalar(select(func.count(Branch.id))) or 0)
    branch_rows = (
        await session.execute(
            select(
                Branch,
                Salon,
                func.ST_Y(cast(Branch.location, Geometry)).label("lat"),
                func.ST_X(cast(Branch.location, Geometry)).label("lng"),
            )
            .join(Salon, Salon.id == Branch.salon_id)
            .order_by(desc(Branch.updated_at), Branch.name.asc())
            .offset(offset)
            .limit(limit)
        )
    ).all()

    salon_ids = {salon.id for _branch, salon, _lat, _lng in branch_rows}
    branch_ids = {branch.id for branch, _salon, _lat, _lng in branch_rows}

    doc_rows: list[SalonDocument] = []
    check_rows: list[VerificationCheck] = []
    inspection_rows: list[Inspection] = []
    if salon_ids and branch_ids:
        doc_rows = list(
            await session.scalars(
                select(SalonDocument)
                .where(
                    SalonDocument.salon_id.in_(salon_ids),
                    (SalonDocument.branch_id.in_(branch_ids)) | (SalonDocument.branch_id.is_(None)),
                )
                .order_by(desc(SalonDocument.created_at))
            )
        )
        check_rows = list(
            await session.scalars(
                select(VerificationCheck)
                .where(
                    VerificationCheck.salon_id.in_(salon_ids),
                    (VerificationCheck.branch_id.in_(branch_ids))
                    | (VerificationCheck.branch_id.is_(None)),
                )
                .order_by(desc(VerificationCheck.updated_at))
            )
        )
        inspection_rows = list(
            await session.scalars(
                select(Inspection)
                .where(
                    Inspection.branch_id.in_(branch_ids),
                    Inspection.overall_outcome != InspectionOutcome.SCHEDULED.value,
                )
                .order_by(desc(Inspection.completed_at).nulls_last(), desc(Inspection.created_at))
            )
        )

    latest_inspection_by_branch: dict[uuid.UUID, Inspection] = {}
    for insp in inspection_rows:
        latest_inspection_by_branch.setdefault(insp.branch_id, insp)

    items: list[dict[str, Any]] = []
    for branch, salon, lat_val, lng_val in branch_rows:
        branch_docs = [
            serialize_document_row(d, storage=storage)
            for d in doc_rows
            if d.salon_id == salon.id and (d.branch_id == branch.id or d.branch_id is None)
        ]
        branch_checks = [
            {
                "id": str(chk.id),
                "check_type": chk.check_type,
                "status": chk.status,
                "notes": chk.notes,
                "updated_at": chk.updated_at.isoformat(),
            }
            for chk in check_rows
            if chk.salon_id == salon.id and (chk.branch_id == branch.id or chk.branch_id is None)
        ]
        latest_insp = latest_inspection_by_branch.get(branch.id)
        items.append(
            {
                "branch_id": str(branch.id),
                "salon_id": str(salon.id),
                "salon_brand_name": salon.brand_name,
                "salon_legal_name": salon.legal_name,
                "salon_status": salon.status,
                "gstin": salon.gstin,
                "pan_masked": salon.pan_masked,
                "branch_name": branch.name,
                "city": branch.city,
                "state": branch.state,
                "lat": float(lat_val),
                "lng": float(lng_val),
                "branch_status": branch.status,
                "verification_status": branch.verification_status,
                "is_featured": branch.is_featured,
                "featured_disclosure_label": branch.featured_disclosure_label,
                "documents": branch_docs,
                "verification_checks": branch_checks,
                "latest_inspection": (
                    serialize_inspection_row(latest_insp) if latest_insp is not None else None
                ),
            }
        )

    return {
        "total": total_count,
        "limit": limit,
        "offset": offset,
        "verification_disclaimer": VERIFICATION_DISCLAIMER,
        "items": items,
    }


@router.patch("/documents/{document_id}")
async def review_salon_document(
    document_id: uuid.UUID,
    payload: ReviewDocumentRequest,
    principal: AdminPrincipalDep,
    session: DbSessionDep,
    storage: StorageProviderDep,
) -> dict[str, Any]:
    """Approve or reject a submitted KYC document and update linked VerificationCheck."""
    doc = await session.scalar(select(SalonDocument).where(SalonDocument.id == document_id))
    if doc is None:
        raise ChairAPIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="DOCUMENT_NOT_FOUND",
            message="KYC document was not found.",
        )

    cleaned_reason = (payload.rejection_reason or "").strip() or None
    if payload.review_status == DocumentReviewStatus.REJECTED.value and not cleaned_reason:
        raise ChairAPIError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="REJECTION_REASON_REQUIRED",
            message="Provide a rejection_reason when rejecting a KYC document.",
        )

    prev_status = doc.review_status
    now_utc = datetime.now(UTC)
    doc.review_status = payload.review_status
    doc.rejection_reason = cleaned_reason if payload.review_status == "REJECTED" else None
    doc.reviewed_by = principal.user.id
    doc.reviewed_at = now_utc
    await session.flush()

    check_type = DOCUMENT_TO_CHECK_TYPE.get(
        doc.document_type, VerificationCheckType.BUSINESS
    ).value
    matching_doc_types = [
        dtype for dtype, ctype in DOCUMENT_TO_CHECK_TYPE.items() if ctype.value == check_type
    ]
    scoped_docs = list(
        await session.scalars(
            select(SalonDocument)
            .where(
                SalonDocument.salon_id == doc.salon_id,
                SalonDocument.branch_id == doc.branch_id,
                SalonDocument.document_type.in_(matching_doc_types),
            )
            .order_by(desc(SalonDocument.created_at))
        )
    )
    latest_by_doc_type: dict[str, SalonDocument] = {}
    for item_doc in scoped_docs:
        latest_by_doc_type.setdefault(item_doc.document_type, item_doc)
    latest_statuses = {d.review_status for d in latest_by_doc_type.values()}
    if DocumentReviewStatus.REJECTED.value in latest_statuses:
        new_check_status = VerificationCheckStatus.FAILED.value
    elif DocumentReviewStatus.APPROVED.value in latest_statuses:
        new_check_status = VerificationCheckStatus.PASSED.value
    else:
        new_check_status = VerificationCheckStatus.PENDING.value

    check_row = await session.scalar(
        select(VerificationCheck).where(
            VerificationCheck.salon_id == doc.salon_id,
            VerificationCheck.branch_id == doc.branch_id,
            VerificationCheck.check_type == check_type,
        )
    )
    if check_row is None:
        try:
            async with session.begin_nested():
                session.add(
                    VerificationCheck(
                        salon_id=doc.salon_id,
                        branch_id=doc.branch_id,
                        check_type=check_type,
                        status=new_check_status,
                        verified_by=principal.user.id,
                        notes=cleaned_reason,
                    )
                )
                await session.flush()
        except IntegrityError:
            existing_row = await session.scalar(
                select(VerificationCheck).where(
                    VerificationCheck.salon_id == doc.salon_id,
                    VerificationCheck.branch_id == doc.branch_id,
                    VerificationCheck.check_type == check_type,
                )
            )
            if existing_row is not None:
                existing_row.status = new_check_status
                existing_row.verified_by = principal.user.id
                existing_row.notes = cleaned_reason
    else:
        check_row.status = new_check_status
        check_row.verified_by = principal.user.id
        check_row.notes = cleaned_reason

    await record_audit_log(
        session,
        actor_user_id=principal.user.id,
        actor_role=principal.primary_role,
        action="KYC_DOCUMENT_REVIEWED",
        resource_type="salon_document",
        resource_id=str(doc.id),
        branch_id=doc.branch_id,
        before_state={"review_status": prev_status},
        after_state={
            "review_status": doc.review_status,
            "rejection_reason": doc.rejection_reason,
        },
        request_id=principal.request_id,
        ip_address=principal.ip_address,
    )
    await session.commit()
    return serialize_document_row(doc, storage=storage)


@router.post("/branches/{branch_id}/inspections", status_code=status.HTTP_201_CREATED)
async def record_branch_hygiene_inspection(
    branch_id: uuid.UUID,
    payload: RecordInspectionRequest,
    principal: AdminPrincipalDep,
    session: DbSessionDep,
) -> dict[str, Any]:
    """Record a physical hygiene inspection enforcing FAILED_CRITICAL safety override."""
    row = (
        await session.execute(
            select(Branch, Salon)
            .join(Salon, Salon.id == Branch.salon_id)
            .where(Branch.id == branch_id)
        )
    ).first()
    if row is None:
        raise ChairAPIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="BRANCH_NOT_FOUND",
            message="Branch not found.",
        )
    branch, salon = row

    evaluation = evaluate_inspection(
        HygieneChecklistInput(
            numerical_score=payload.numerical_score,
            single_use_blades_ok=payload.single_use_blades_ok,
            sharps_disposal_ok=payload.sharps_disposal_ok,
            instrument_disinfection_ok=payload.instrument_disinfection_ok,
            fresh_towels_ok=payload.fresh_towels_ok,
        )
    )
    now_utc = datetime.now(UTC)
    if payload.reinspection_due_at is not None and payload.reinspection_due_at.tzinfo is None:
        raise ChairAPIError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="TIMEZONE_REQUIRED",
            message="reinspection_due_at must include timezone offset.",
        )
    reinspection_utc = (
        payload.reinspection_due_at.astimezone(UTC) if payload.reinspection_due_at else None
    )
    inspection = Inspection(
        branch_id=branch.id,
        inspector_user_id=principal.user.id,
        scheduled_at=now_utc,
        completed_at=now_utc,
        numerical_score=payload.numerical_score,
        single_use_blades_ok=payload.single_use_blades_ok,
        sharps_disposal_ok=payload.sharps_disposal_ok,
        instrument_disinfection_ok=payload.instrument_disinfection_ok,
        fresh_towels_ok=payload.fresh_towels_ok,
        overall_outcome=evaluation.outcome.value,
        corrective_action_notes=(payload.corrective_action_notes or "").strip() or None,
        reinspection_due_at=reinspection_utc,
        evidence_keys_json=list(payload.evidence_keys),
    )
    session.add(inspection)
    await session.flush()

    prev_branch_state = {
        "status": branch.status,
        "verification_status": branch.verification_status,
    }
    branch.verification_status = evaluation.resulting_verification_status.value
    if evaluation.outcome == InspectionOutcome.FAILED_CRITICAL:
        branch.status = BranchStatus.SUSPENDED.value
        salon.verification_badge_status = "SUSPENDED"
    elif evaluation.outcome == InspectionOutcome.PASSED:
        if salon.status != SalonStatus.SUSPENDED.value:
            if branch.status in {BranchStatus.DRAFT.value, BranchStatus.SUSPENDED.value}:
                branch.status = BranchStatus.ACTIVE.value
            salon.status = SalonStatus.ACTIVE.value
            salon.verification_badge_status = "VERIFIED"

    phys_check = await session.scalar(
        select(VerificationCheck).where(
            VerificationCheck.salon_id == salon.id,
            VerificationCheck.branch_id == branch.id,
            VerificationCheck.check_type == VerificationCheckType.PHYSICAL_INSPECTION.value,
        )
    )
    check_status = (
        VerificationCheckStatus.PASSED.value
        if evaluation.outcome == InspectionOutcome.PASSED
        else VerificationCheckStatus.FAILED.value
    )
    if phys_check is None:
        session.add(
            VerificationCheck(
                salon_id=salon.id,
                branch_id=branch.id,
                check_type=VerificationCheckType.PHYSICAL_INSPECTION.value,
                status=check_status,
                verified_by=principal.user.id,
                notes=inspection.corrective_action_notes,
            )
        )
    else:
        phys_check.status = check_status
        phys_check.verified_by = principal.user.id
        phys_check.notes = inspection.corrective_action_notes

    await record_audit_log(
        session,
        actor_user_id=principal.user.id,
        actor_role=principal.primary_role,
        action="HYGIENE_INSPECTION_RECORDED",
        resource_type="inspection",
        resource_id=str(inspection.id),
        branch_id=branch.id,
        before_state=prev_branch_state,
        after_state={
            "overall_outcome": inspection.overall_outcome,
            "numerical_score": inspection.numerical_score,
            "failed_critical_checks": list(evaluation.failed_critical_checks),
            "branch_status": branch.status,
            "verification_status": branch.verification_status,
        },
        request_id=principal.request_id,
        ip_address=principal.ip_address,
    )
    await session.commit()
    return {
        "inspection": serialize_inspection_row(inspection),
        "failed_critical_checks": list(evaluation.failed_critical_checks),
        "branch_status": branch.status,
        "verification_status": branch.verification_status,
    }


@router.patch("/branches/{branch_id}/governance")
async def update_branch_governance(
    branch_id: uuid.UUID,
    payload: BranchGovernanceRequest,
    principal: AdminPrincipalDep,
    session: DbSessionDep,
) -> dict[str, Any]:
    """Update branch activation/suspension, verification tier, and featured disclosure label."""
    row = (
        await session.execute(
            select(Branch, Salon)
            .join(Salon, Salon.id == Branch.salon_id)
            .where(Branch.id == branch_id)
        )
    ).first()
    if row is None:
        raise ChairAPIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="BRANCH_NOT_FOUND",
            message="Branch not found.",
        )
    branch, salon = row

    prev_state = {
        "status": branch.status,
        "verification_status": branch.verification_status,
        "is_featured": branch.is_featured,
        "featured_disclosure_label": branch.featured_disclosure_label,
    }

    latest_insp = await get_latest_completed_inspection(session, branch.id)
    if (
        latest_insp is not None
        and latest_insp.overall_outcome == InspectionOutcome.FAILED_CRITICAL.value
    ):
        attempt_activate = payload.status == BranchStatus.ACTIVE
        attempt_clear_suspended = (
            payload.verification_status is not None
            and payload.verification_status != BranchVerificationStatus.SUSPENDED
        )
        if attempt_activate or attempt_clear_suspended:
            raise ChairAPIError(
                status_code=status.HTTP_409_CONFLICT,
                code="FAILED_CRITICAL_REINSPECTION_REQUIRED",
                message=(
                    "Branches suspended after FAILED_CRITICAL require a passing re-inspection "
                    "before activation or verification recovery."
                ),
            )

    if payload.verification_status == BranchVerificationStatus.CHAIR_VERIFIED:
        if latest_insp is None or latest_insp.overall_outcome != InspectionOutcome.PASSED.value:
            raise ChairAPIError(
                status_code=status.HTTP_409_CONFLICT,
                code="PASSED_INSPECTION_REQUIRED",
                message="CHAIR_VERIFIED status requires a passing hygiene inspection.",
            )

    next_status = payload.status.value if payload.status is not None else branch.status
    next_verif = (
        payload.verification_status.value
        if payload.verification_status is not None
        else branch.verification_status
    )
    if (
        next_status == BranchStatus.ACTIVE.value
        and next_verif == BranchVerificationStatus.SUSPENDED.value
    ):
        raise ChairAPIError(
            status_code=status.HTTP_409_CONFLICT,
            code="SUSPENDED_VERIFICATION_BLOCKS_ACTIVATION",
            message="Cannot activate a branch while verification status is SUSPENDED.",
        )
    if next_status == BranchStatus.ACTIVE.value and salon.status == SalonStatus.SUSPENDED.value:
        raise ChairAPIError(
            status_code=status.HTTP_409_CONFLICT,
            code="SALON_SUSPENDED",
            message="Cannot activate a branch belonging to a suspended salon.",
        )

    next_featured = branch.is_featured if payload.is_featured is None else payload.is_featured
    if payload.featured_disclosure_label is not None:
        next_label = payload.featured_disclosure_label.strip() or None
    else:
        next_label = branch.featured_disclosure_label

    if next_featured and not next_label:
        raise ChairAPIError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="FEATURED_DISCLOSURE_REQUIRED",
            message="Featured placement requires an explicit featured_disclosure_label.",
        )

    if payload.status is not None:
        branch.status = payload.status.value
        if payload.status == BranchStatus.ACTIVE and salon.status in {
            SalonStatus.DRAFT.value,
            SalonStatus.PENDING_REVIEW.value,
        }:
            salon.status = SalonStatus.ACTIVE.value
    if payload.verification_status is not None:
        branch.verification_status = payload.verification_status.value
        if payload.verification_status == BranchVerificationStatus.SUSPENDED:
            salon.verification_badge_status = "SUSPENDED"
        elif payload.verification_status == BranchVerificationStatus.CHAIR_VERIFIED:
            salon.verification_badge_status = "VERIFIED"
    branch.is_featured = next_featured
    branch.featured_disclosure_label = next_label if next_featured else None

    await record_audit_log(
        session,
        actor_user_id=principal.user.id,
        actor_role=principal.primary_role,
        action="BRANCH_GOVERNANCE_UPDATED",
        resource_type="branch",
        resource_id=str(branch.id),
        branch_id=branch.id,
        before_state=prev_state,
        after_state={
            "status": branch.status,
            "verification_status": branch.verification_status,
            "is_featured": branch.is_featured,
            "featured_disclosure_label": branch.featured_disclosure_label,
            "notes": (payload.notes or "").strip() or None,
        },
        request_id=principal.request_id,
        ip_address=principal.ip_address,
    )
    await session.commit()
    return {
        "branch_id": str(branch.id),
        "salon_status": salon.status,
        "status": branch.status,
        "verification_status": branch.verification_status,
        "is_featured": branch.is_featured,
        "featured_disclosure_label": branch.featured_disclosure_label,
    }

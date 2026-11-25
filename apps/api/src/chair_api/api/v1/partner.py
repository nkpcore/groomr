"""Partner-scoped workspace and tenant isolation endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import or_, select

from chair_api.api.deps import DbSessionDep
from chair_api.db.models import Branch, Salon
from chair_api.domain.enums import UserRole
from chair_api.security.rbac import AuthPrincipal, assert_branch_access, require_roles

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

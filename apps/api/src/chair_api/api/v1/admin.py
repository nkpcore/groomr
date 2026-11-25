"""Admin-only governance and security audit log endpoints."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, select

from chair_api.api.deps import DbSessionDep
from chair_api.db.models import AuditLog
from chair_api.domain.enums import UserRole
from chair_api.security.rbac import AuthPrincipal, require_roles

router = APIRouter()
AdminPrincipalDep = Annotated[AuthPrincipal, Depends(require_roles(UserRole.ADMIN))]


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


@router.get("/audit-logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    _principal: AdminPrincipalDep,
    session: DbSessionDep,
    limit: int = Query(default=25, ge=1, le=100),
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

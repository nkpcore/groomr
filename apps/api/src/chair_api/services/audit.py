"""Append-only audit trail recorder."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from chair_api.db.models import AuditLog


async def record_audit_log(
    session: AsyncSession,
    *,
    actor_user_id: uuid.UUID | None,
    actor_role: str,
    action: str,
    resource_type: str,
    resource_id: str,
    branch_id: uuid.UUID | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    request_id: str | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    """Append an audit log entry inside the active transaction."""
    entry = AuditLog(
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        branch_id=branch_id,
        before_state_json=before_state,
        after_state_json=after_state,
        request_id=request_id,
        ip_address=ip_address,
    )
    session.add(entry)
    return entry

"""PostgreSQL-backed HTTP request idempotency enforcement."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import status
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from chair_api.core.errors import ChairAPIError
from chair_api.db.models import IdempotencyKey

DEFAULT_IDEMPOTENCY_TTL_HOURS = 24


@dataclass(frozen=True, slots=True)
class IdempotencyReplay:
    status_code: int
    body: dict[str, Any]


def require_idempotency_key(raw_key: str | None) -> str:
    """Validate required Idempotency-Key header."""
    if raw_key is None or not raw_key.strip():
        raise ChairAPIError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="IDEMPOTENCY_KEY_REQUIRED",
            message="Idempotency-Key header is required for this operation.",
        )
    cleaned = raw_key.strip()
    if len(cleaned) > 128:
        raise ChairAPIError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="INVALID_IDEMPOTENCY_KEY",
            message="Idempotency-Key header must not exceed 128 characters.",
        )
    return cleaned


def compute_request_hash(payload: Any) -> str:
    """Compute canonical SHA-256 hash of a normalized JSON-serializable payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def acquire_idempotency_replay(
    session: AsyncSession,
    *,
    actor_key: str,
    endpoint: str,
    idempotency_key: str,
    request_hash: str,
    now_utc: datetime | None = None,
) -> IdempotencyReplay | None:
    """Lock the (actor, endpoint, key) scope and return prior response if valid."""
    current_utc = now_utc or datetime.now(UTC)
    lock_seed = f"idem:{actor_key}:{endpoint}:{idempotency_key}"
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:seed))"),
        {"seed": lock_seed},
    )

    existing = await session.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.actor_key == actor_key,
            IdempotencyKey.endpoint == endpoint,
            IdempotencyKey.idempotency_key == idempotency_key,
        )
    )
    if existing is None:
        return None

    if existing.expires_at <= current_utc:
        await session.execute(delete(IdempotencyKey).where(IdempotencyKey.id == existing.id))
        await session.flush()
        return None

    if existing.request_hash != request_hash:
        raise ChairAPIError(
            status_code=status.HTTP_409_CONFLICT,
            code="IDEMPOTENCY_KEY_CONFLICT",
            message="Idempotency-Key was already used with a different request payload.",
        )

    return IdempotencyReplay(
        status_code=existing.response_status,
        body=existing.response_body_json,
    )


async def record_idempotency_response(
    session: AsyncSession,
    *,
    actor_key: str,
    endpoint: str,
    idempotency_key: str,
    request_hash: str,
    response_status: int,
    response_body: dict[str, Any],
    now_utc: datetime | None = None,
) -> None:
    """Persist serialized response payload inside active DB transaction."""
    current_utc = now_utc or datetime.now(UTC)
    row = IdempotencyKey(
        actor_key=actor_key,
        endpoint=endpoint,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        response_status=response_status,
        response_body_json=response_body,
        expires_at=current_utc + timedelta(hours=DEFAULT_IDEMPOTENCY_TTL_HOURS),
    )
    session.add(row)
    await session.flush()

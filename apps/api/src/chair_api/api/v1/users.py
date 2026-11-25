"""Authenticated user profile, locale, and DPDP consent endpoints."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from chair_api.api.deps import DbSessionDep, SettingsDep
from chair_api.core.config import Settings
from chair_api.core.errors import ChairAPIError
from chair_api.db.models import UserConsent
from chair_api.domain.enums import ConsentType, UserRole
from chair_api.security.rbac import AuthPrincipal, CurrentPrincipalDep
from chair_api.services.audit import record_audit_log

router = APIRouter()
_EMAIL_REGEX = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class RoleScopeOut(BaseModel):
    id: uuid.UUID
    role: UserRole
    salon_id: uuid.UUID | None
    branch_id: uuid.UUID | None


class CurrentConsentState(BaseModel):
    consent_type: ConsentType
    granted: bool
    version: str
    granted_at: datetime | None
    revoked_at: datetime | None


class ConsentHistoryItem(BaseModel):
    id: uuid.UUID
    consent_type: ConsentType
    version: str
    granted: bool
    granted_at: datetime
    revoked_at: datetime | None
    created_at: datetime


class ConsentsResponse(BaseModel):
    consents: list[CurrentConsentState]
    history: list[ConsentHistoryItem]


class UserProfileResponse(BaseModel):
    id: uuid.UUID
    phone_e164: str
    email: str | None
    full_name: str | None
    preferred_locale: Literal["en", "hi"]
    is_active: bool
    last_login_at: datetime | None
    roles: list[RoleScopeOut]
    consents: list[CurrentConsentState]


class UpdateProfileRequest(BaseModel):
    full_name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=255, pattern=_EMAIL_REGEX)
    preferred_locale: Literal["en", "hi"] | None = None

    @field_validator("full_name", mode="before")
    @classmethod
    def _normalize_name(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped if stripped else None
        return value

    @field_validator("email", mode="before")
    @classmethod
    def _normalize_email(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip().lower()
            return stripped if stripped else None
        return value


class ConsentDecisionInput(BaseModel):
    consent_type: ConsentType
    granted: bool
    version: str = Field(default="v1.0", min_length=1, max_length=32)


class UpdateConsentsRequest(BaseModel):
    decisions: list[ConsentDecisionInput] = Field(min_length=1, max_length=10)

    @field_validator("decisions")
    @classmethod
    def _reject_duplicate_types(
        cls, decisions: list[ConsentDecisionInput]
    ) -> list[ConsentDecisionInput]:
        seen: set[ConsentType] = set()
        for item in decisions:
            if item.consent_type in seen:
                raise ValueError(f"Duplicate consent_type in request: {item.consent_type.value}")
            seen.add(item.consent_type)
        return decisions


async def _fetch_latest_consent_rows(
    session: AsyncSession, *, user_id: uuid.UUID
) -> tuple[list[UserConsent], dict[ConsentType, UserConsent]]:
    rows = list(
        await session.scalars(
            select(UserConsent)
            .where(UserConsent.user_id == user_id)
            .order_by(desc(UserConsent.created_at), desc(UserConsent.id))
        )
    )
    latest_by_type: dict[ConsentType, UserConsent] = {}
    for row in rows:
        ctype = ConsentType(row.consent_type)
        if ctype not in latest_by_type:
            latest_by_type[ctype] = row
    return rows, latest_by_type


async def _load_consents_payload(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    default_version: str,
) -> ConsentsResponse:
    rows, latest_by_type = await _fetch_latest_consent_rows(session, user_id=user_id)

    summary: list[CurrentConsentState] = []
    for ctype in ConsentType:
        latest = latest_by_type.get(ctype)
        if latest is None:
            summary.append(
                CurrentConsentState(
                    consent_type=ctype,
                    granted=False,
                    version=default_version,
                    granted_at=None,
                    revoked_at=None,
                )
            )
        else:
            summary.append(
                CurrentConsentState(
                    consent_type=ctype,
                    granted=latest.granted,
                    version=latest.version,
                    granted_at=latest.granted_at if latest.granted else None,
                    revoked_at=latest.revoked_at,
                )
            )

    history = [
        ConsentHistoryItem(
            id=row.id,
            consent_type=ConsentType(row.consent_type),
            version=row.version,
            granted=row.granted,
            granted_at=row.granted_at,
            revoked_at=row.revoked_at,
            created_at=row.created_at,
        )
        for row in rows[:50]
    ]
    return ConsentsResponse(consents=summary, history=history)


async def _build_profile_response(
    session: AsyncSession,
    *,
    principal: AuthPrincipal,
    settings: Settings,
) -> UserProfileResponse:
    consents_payload = await _load_consents_payload(
        session,
        user_id=principal.user.id,
        default_version=settings.consent_policy_version,
    )
    return UserProfileResponse(
        id=principal.user.id,
        phone_e164=principal.user.phone_e164,
        email=principal.user.email,
        full_name=principal.user.full_name,
        preferred_locale="hi" if principal.user.preferred_locale == "hi" else "en",
        is_active=principal.user.is_active,
        last_login_at=principal.user.last_login_at,
        roles=[
            RoleScopeOut(
                id=scope.id,
                role=scope.role,
                salon_id=scope.salon_id,
                branch_id=scope.branch_id,
            )
            for scope in principal.roles
        ],
        consents=consents_payload.consents,
    )


@router.get("/me", response_model=UserProfileResponse)
async def get_me(
    principal: CurrentPrincipalDep,
    session: DbSessionDep,
    settings: SettingsDep,
) -> UserProfileResponse:
    """Return current user's profile, role scopes, and effective DPDP consent state."""
    return await _build_profile_response(session, principal=principal, settings=settings)


@router.patch("/me", response_model=UserProfileResponse)
async def update_me(
    payload: UpdateProfileRequest,
    principal: CurrentPrincipalDep,
    session: DbSessionDep,
    settings: SettingsDep,
) -> UserProfileResponse:
    """Update authenticated user's display name, email, or locale preference."""
    user = principal.user
    before_locale = user.preferred_locale
    before_has_name = bool(user.full_name)
    before_has_email = bool(user.email)
    changed_fields: list[str] = []

    provided_fields = payload.model_fields_set
    if "full_name" in provided_fields and payload.full_name != user.full_name:
        user.full_name = payload.full_name
        changed_fields.append("full_name")
    if "email" in provided_fields and payload.email != user.email:
        user.email = payload.email
        changed_fields.append("email")
    if (
        "preferred_locale" in provided_fields
        and payload.preferred_locale is not None
        and payload.preferred_locale != user.preferred_locale
    ):
        user.preferred_locale = payload.preferred_locale
        changed_fields.append("preferred_locale")

    if changed_fields:
        await record_audit_log(
            session,
            actor_user_id=user.id,
            actor_role=principal.primary_role,
            action="USER_PROFILE_UPDATED",
            resource_type="user",
            resource_id=str(user.id),
            before_state={
                "has_full_name": before_has_name,
                "has_email": before_has_email,
                "preferred_locale": before_locale,
            },
            after_state={
                "changed_fields": changed_fields,
                "has_full_name": bool(user.full_name),
                "has_email": bool(user.email),
                "preferred_locale": user.preferred_locale,
            },
            request_id=principal.request_id,
            ip_address=principal.ip_hash,
        )
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise ChairAPIError(
                status_code=status.HTTP_409_CONFLICT,
                code="EMAIL_ALREADY_IN_USE",
                message="That email address is already registered to another account.",
            ) from exc
        await session.refresh(user)

    return await _build_profile_response(session, principal=principal, settings=settings)


@router.get("/me/consents", response_model=ConsentsResponse)
async def get_my_consents(
    principal: CurrentPrincipalDep,
    session: DbSessionDep,
    settings: SettingsDep,
) -> ConsentsResponse:
    """Return effective DPDP consent state and historical audit entries."""
    return await _load_consents_payload(
        session,
        user_id=principal.user.id,
        default_version=settings.consent_policy_version,
    )


@router.put("/me/consents", response_model=ConsentsResponse)
async def update_my_consents(
    payload: UpdateConsentsRequest,
    principal: CurrentPrincipalDep,
    session: DbSessionDep,
    settings: SettingsDep,
) -> ConsentsResponse:
    """Record DPDP consent grants and revocations while skipping unchanged duplicates."""
    for decision in payload.decisions:
        if decision.version != settings.consent_policy_version:
            raise ChairAPIError(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                code="INVALID_CONSENT_VERSION",
                message=f"Consent policy version must be {settings.consent_policy_version}.",
            )

    _, latest_by_type = await _fetch_latest_consent_rows(session, user_id=principal.user.id)
    now = datetime.now(UTC)
    user_agent = principal.user_agent[:255] if principal.user_agent else None

    changed_after: dict[str, dict[str, object]] = {}
    before_changed: dict[str, bool] = {}

    for decision in payload.decisions:
        latest = latest_by_type.get(decision.consent_type)
        if (
            latest is not None
            and latest.granted == decision.granted
            and latest.version == decision.version
        ):
            continue

        before_changed[decision.consent_type.value] = bool(latest.granted) if latest else False
        changed_after[decision.consent_type.value] = {
            "granted": decision.granted,
            "version": decision.version,
        }
        prior_granted_at = latest.granted_at if (latest is not None and latest.granted) else now
        row = UserConsent(
            user_id=principal.user.id,
            consent_type=decision.consent_type.value,
            version=decision.version,
            granted=decision.granted,
            granted_at=now if decision.granted else prior_granted_at,
            revoked_at=None if decision.granted else now,
            ip_hash=principal.ip_hash,
            user_agent=user_agent,
        )
        session.add(row)

    if changed_after:
        await record_audit_log(
            session,
            actor_user_id=principal.user.id,
            actor_role=principal.primary_role,
            action="USER_CONSENT_UPDATED",
            resource_type="user_consent",
            resource_id=str(principal.user.id),
            before_state=before_changed,
            after_state=changed_after,
            request_id=principal.request_id,
            ip_address=principal.ip_hash,
        )
        await session.commit()

    return await _load_consents_payload(
        session,
        user_id=principal.user.id,
        default_version=settings.consent_policy_version,
    )

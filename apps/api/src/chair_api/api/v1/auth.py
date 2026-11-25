"""Phone OTP authentication, atomic JWT rotation, and logout endpoints."""

import secrets
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from chair_api.api.deps import AuthStoreDep, DbSessionDep, OTPProviderDep, SettingsDep
from chair_api.core.auth_store import AuthStore, OTPChallengeRecord, RefreshFamilyRecord
from chair_api.core.config import Settings
from chair_api.core.errors import ChairAPIError
from chair_api.db.models import User, UserRoleAssignment
from chair_api.domain.enums import UserRole
from chair_api.security.rbac import extract_client_ip, highest_precedence_role
from chair_api.security.tokens import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_client_ip,
    hash_token_jti,
)
from chair_api.services.audit import record_audit_log

router = APIRouter()
_optional_bearer = HTTPBearer(auto_error=False)
_OptionalBearerDep = Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)]
_E164_REGEX = r"^\+[1-9]\d{7,14}$"
_OTP_REGEX = r"^\d{6}$"


class OTPRequestPayload(BaseModel):
    phone_e164: str = Field(
        pattern=_E164_REGEX,
        description="E.164 phone number e.g. +919000000003",
    )


class OTPRequestResponse(BaseModel):
    challenge_id: str
    masked_phone: str
    expires_in_seconds: int
    delivery_mode: str


class OTPVerifyPayload(BaseModel):
    challenge_id: str = Field(min_length=8, max_length=128)
    phone_e164: str = Field(pattern=_E164_REGEX)
    otp_code: str = Field(pattern=_OTP_REGEX)


class AuthTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_in_seconds: int
    refresh_expires_in_seconds: int
    user_id: uuid.UUID
    roles: list[UserRole]
    preferred_locale: Literal["en", "hi"]


class RefreshTokenPayload(BaseModel):
    refresh_token: str = Field(min_length=16, max_length=2048)


class LogoutResponse(BaseModel):
    status: Literal["logged_out"]


def _mask_phone(phone_e164: str) -> str:
    if len(phone_e164) <= 6:
        return "***"
    return f"{phone_e164[:3]}{'*' * (len(phone_e164) - 7)}{phone_e164[-4:]}"


async def _load_active_user_roles(
    session: AsyncSession, *, user_id: uuid.UUID
) -> tuple[User | None, list[UserRole]]:
    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None or not user.is_active:
        return None, []
    role_rows = list(
        await session.scalars(
            select(UserRoleAssignment).where(UserRoleAssignment.user_id == user.id)
        )
    )
    roles = sorted({UserRole(r.role) for r in role_rows}, key=lambda r: r.value)
    return user, roles


async def _get_or_create_user_with_default_role(
    session: AsyncSession, *, phone_e164: str
) -> tuple[User, list[UserRole], bool]:
    user = await session.scalar(select(User).where(User.phone_e164 == phone_e164))
    is_new_user = False

    if user is None:
        user = User(phone_e164=phone_e164, preferred_locale="en", is_active=True)
        session.add(user)
        try:
            await session.flush()
            is_new_user = True
        except IntegrityError:
            await session.rollback()
            user = await session.scalar(select(User).where(User.phone_e164 == phone_e164))
            if user is None:
                raise

    if not user.is_active:
        raise ChairAPIError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="ACCOUNT_INACTIVE",
            message="This user account is suspended or inactive.",
        )

    role_rows = list(
        await session.scalars(
            select(UserRoleAssignment).where(UserRoleAssignment.user_id == user.id)
        )
    )
    if not role_rows:
        default_role = UserRoleAssignment(user_id=user.id, role=UserRole.CUSTOMER.value)
        session.add(default_role)
        await session.flush()
        role_rows = [default_role]

    distinct_roles = sorted({UserRole(row.role) for row in role_rows}, key=lambda r: r.value)
    return user, distinct_roles, is_new_user


def _build_token_response(
    *,
    access_jwt: str,
    refresh_jwt: str,
    user: User,
    roles: list[UserRole],
    settings: Settings,
) -> AuthTokenResponse:
    return AuthTokenResponse(
        access_token=access_jwt,
        refresh_token=refresh_jwt,
        expires_in_seconds=settings.jwt_access_ttl_minutes * 60,
        refresh_expires_in_seconds=settings.jwt_refresh_ttl_days * 86400,
        user_id=user.id,
        roles=roles,
        preferred_locale="hi" if user.preferred_locale == "hi" else "en",
    )


async def _issue_new_session_tokens(
    *,
    user: User,
    roles: list[UserRole],
    family_id: str,
    settings: Settings,
    auth_store: AuthStore,
) -> AuthTokenResponse:
    now = datetime.now(UTC)
    access_jwt, _ = create_access_token(
        user_id=user.id, settings=settings, family_id=family_id, now=now
    )
    refresh_jwt, refresh_claims = create_refresh_token(
        user_id=user.id, family_id=family_id, settings=settings, now=now
    )
    refresh_ttl_seconds = settings.jwt_refresh_ttl_days * 86400
    await auth_store.save_refresh_family(
        RefreshFamilyRecord(
            family_id=family_id,
            user_id=str(user.id),
            active_jti_hash=hash_token_jti(refresh_claims.jti),
            revoked=False,
        ),
        ttl_seconds=refresh_ttl_seconds,
    )
    return _build_token_response(
        access_jwt=access_jwt,
        refresh_jwt=refresh_jwt,
        user=user,
        roles=roles,
        settings=settings,
    )


@router.post("/otp/request", response_model=OTPRequestResponse)
async def request_otp(
    payload: OTPRequestPayload,
    request: Request,
    settings: SettingsDep,
    auth_store: AuthStoreDep,
    otp_provider: OTPProviderDep,
) -> OTPRequestResponse:
    """Issue an SMS OTP challenge subject to IP and phone rate limits."""
    ip_address = extract_client_ip(request, settings)
    ip_key = hash_client_ip(ip_address or "unknown", secret_key=settings.secret_key) or "unknown"

    retry_after = await auth_store.check_and_increment_otp_rate_limit(
        phone_e164=payload.phone_e164,
        ip_key=ip_key,
        window_seconds=settings.otp_request_window_seconds,
        max_per_phone=settings.otp_request_max_per_phone,
        max_per_ip=settings.otp_request_max_per_ip,
    )
    if retry_after is not None:
        raise ChairAPIError(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="OTP_RATE_LIMITED",
            message="Too many OTP requests. Please try again later.",
            details={"retry_after_seconds": retry_after},
        )

    await otp_provider.send_otp(payload.phone_e164)
    challenge_id = secrets.token_urlsafe(24)
    await auth_store.save_otp_challenge(
        OTPChallengeRecord(
            challenge_id=challenge_id,
            phone_e164=payload.phone_e164,
            provider=settings.auth_otp_provider,
            attempts=0,
            created_at_iso=datetime.now(UTC).isoformat(),
        ),
        ttl_seconds=settings.otp_ttl_seconds,
    )
    return OTPRequestResponse(
        challenge_id=challenge_id,
        masked_phone=_mask_phone(payload.phone_e164),
        expires_in_seconds=settings.otp_ttl_seconds,
        delivery_mode=settings.auth_otp_provider,
    )


@router.post("/otp/verify", response_model=AuthTokenResponse)
async def verify_otp(
    payload: OTPVerifyPayload,
    request: Request,
    session: DbSessionDep,
    settings: SettingsDep,
    auth_store: AuthStoreDep,
    otp_provider: OTPProviderDep,
) -> AuthTokenResponse:
    """Atomically claim/verify OTP challenge and issue access + rotating refresh JWTs."""
    locked_ttl = await auth_store.is_phone_verify_locked(
        payload.phone_e164, max_failures=settings.otp_verify_max_failures_per_window
    )
    if locked_ttl is not None:
        raise ChairAPIError(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="OTP_MAX_ATTEMPTS_EXCEEDED",
            message="Too many failed verification attempts. Try again later.",
            details={"retry_after_seconds": locked_ttl},
        )

    claim_state, attempts = await auth_store.claim_otp_attempt(
        challenge_id=payload.challenge_id,
        expected_phone=payload.phone_e164,
        max_attempts=settings.otp_verify_max_attempts,
    )
    if claim_state == "missing":
        raise ChairAPIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_OR_EXPIRED_OTP",
            message="OTP challenge is invalid or has expired.",
        )
    if claim_state == "locked":
        raise ChairAPIError(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="OTP_MAX_ATTEMPTS_EXCEEDED",
            message="Maximum verification attempts reached. Request a new OTP.",
        )

    verified = await otp_provider.verify_otp(payload.phone_e164, payload.otp_code)
    if not verified:
        phone_locked = await auth_store.record_otp_verify_failure(
            phone_e164=payload.phone_e164,
            window_seconds=settings.otp_request_window_seconds,
            max_failures=settings.otp_verify_max_failures_per_window,
        )
        if attempts >= settings.otp_verify_max_attempts or phone_locked is not None:
            await auth_store.consume_otp_challenge(payload.challenge_id)
            raise ChairAPIError(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                code="OTP_MAX_ATTEMPTS_EXCEEDED",
                message="Maximum verification attempts reached. Request a new OTP.",
            )
        raise ChairAPIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_OR_EXPIRED_OTP",
            message="Verification code is incorrect.",
            details={"attempts_remaining": max(0, settings.otp_verify_max_attempts - attempts)},
        )

    consumed = await auth_store.consume_otp_challenge(payload.challenge_id)
    if not consumed:
        raise ChairAPIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_OR_EXPIRED_OTP",
            message="OTP challenge was already used or has expired.",
        )
    await auth_store.clear_otp_verify_failures(payload.phone_e164)

    user, roles, is_new_user = await _get_or_create_user_with_default_role(
        session, phone_e164=payload.phone_e164
    )
    now = datetime.now(UTC)
    user.last_login_at = now

    family_id = uuid.uuid4().hex
    token_response = await _issue_new_session_tokens(
        user=user,
        roles=roles,
        family_id=family_id,
        settings=settings,
        auth_store=auth_store,
    )

    ip_hash = hash_client_ip(extract_client_ip(request, settings), secret_key=settings.secret_key)
    await record_audit_log(
        session,
        actor_user_id=user.id,
        actor_role=highest_precedence_role(roles),
        action="USER_LOGIN",
        resource_type="user",
        resource_id=str(user.id),
        after_state={
            "is_new_user": is_new_user,
            "roles": [r.value for r in roles],
            "provider": settings.auth_otp_provider,
        },
        request_id=getattr(request.state, "request_id", None),
        ip_address=ip_hash,
    )
    await session.commit()
    return token_response


@router.post("/refresh", response_model=AuthTokenResponse)
async def refresh_tokens(
    payload: RefreshTokenPayload,
    request: Request,
    session: DbSessionDep,
    settings: SettingsDep,
    auth_store: AuthStoreDep,
) -> AuthTokenResponse:
    """Atomically rotate refresh token with CAS and replay detection."""
    claims = decode_token(payload.refresh_token, settings=settings, expected_typ="refresh")
    assert claims.fam is not None

    user, roles = await _load_active_user_roles(session, user_id=claims.sub)
    refresh_ttl_seconds = settings.jwt_refresh_ttl_days * 86400
    if user is None:
        await auth_store.revoke_refresh_family(claims.fam, ttl_seconds=refresh_ttl_seconds)
        raise ChairAPIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="ACCOUNT_INACTIVE",
            message="User account does not exist or is inactive.",
        )

    now = datetime.now(UTC)
    access_jwt, _ = create_access_token(
        user_id=user.id, settings=settings, family_id=claims.fam, now=now
    )
    refresh_jwt, next_refresh_claims = create_refresh_token(
        user_id=user.id, family_id=claims.fam, settings=settings, now=now
    )

    outcome = await auth_store.rotate_refresh_family(
        family_id=claims.fam,
        expected_user_id=str(user.id),
        expected_jti_hash=hash_token_jti(claims.jti),
        new_jti_hash=hash_token_jti(next_refresh_claims.jti),
        ttl_seconds=refresh_ttl_seconds,
    )
    if outcome == "reused":
        ip_hash = hash_client_ip(
            extract_client_ip(request, settings), secret_key=settings.secret_key
        )
        await record_audit_log(
            session,
            actor_user_id=claims.sub,
            actor_role="SYSTEM",
            action="AUTH_REFRESH_REUSE_DETECTED",
            resource_type="auth_session",
            resource_id=claims.fam,
            after_state={"revoked": True},
            request_id=getattr(request.state, "request_id", None),
            ip_address=ip_hash,
        )
        await session.commit()
        raise ChairAPIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="REFRESH_TOKEN_REUSED",
            message="Refresh token reuse detected. Session has been revoked.",
        )
    if outcome in ("missing", "revoked"):
        raise ChairAPIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_REFRESH_TOKEN",
            message="Refresh session is invalid or has been revoked.",
        )

    return _build_token_response(
        access_jwt=access_jwt,
        refresh_jwt=refresh_jwt,
        user=user,
        roles=roles,
        settings=settings,
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    payload: RefreshTokenPayload,
    request: Request,
    credentials: _OptionalBearerDep,
    session: DbSessionDep,
    settings: SettingsDep,
    auth_store: AuthStoreDep,
) -> LogoutResponse:
    """Revoke refresh token family cleanly even if the caller's access token has expired."""
    refresh_claims = decode_token(payload.refresh_token, settings=settings, expected_typ="refresh")
    assert refresh_claims.fam is not None

    if credentials is not None and credentials.scheme.lower() == "bearer":
        try:
            access_claims = decode_token(
                credentials.credentials, settings=settings, expected_typ="access"
            )
            if access_claims.sub != refresh_claims.sub:
                raise ChairAPIError(
                    status_code=status.HTTP_403_FORBIDDEN,
                    code="FORBIDDEN",
                    message="Session token does not belong to the authenticated user.",
                )
        except ChairAPIError as exc:
            if exc.code != "TOKEN_EXPIRED":
                raise

    refresh_ttl_seconds = settings.jwt_refresh_ttl_days * 86400
    await auth_store.revoke_refresh_family(refresh_claims.fam, ttl_seconds=refresh_ttl_seconds)

    ip_hash = hash_client_ip(extract_client_ip(request, settings), secret_key=settings.secret_key)
    await record_audit_log(
        session,
        actor_user_id=refresh_claims.sub,
        actor_role="USER",
        action="USER_LOGOUT",
        resource_type="auth_session",
        resource_id=refresh_claims.fam,
        request_id=getattr(request.state, "request_id", None),
        ip_address=ip_hash,
    )
    await session.commit()
    return LogoutResponse(status="logged_out")

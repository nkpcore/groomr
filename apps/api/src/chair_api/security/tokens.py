"""JWT creation/verification and cryptographic hashing helpers."""

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

import jwt
from fastapi import status

from chair_api.core.config import Settings
from chair_api.core.errors import ChairAPIError

JWT_ISSUER = "chair-api"
JWT_AUDIENCE = "chair-clients"
JWT_ALGORITHM = "HS256"


@dataclass(frozen=True, slots=True)
class TokenClaims:
    sub: uuid.UUID
    typ: Literal["access", "refresh"]
    jti: str
    fam: str | None
    iat: datetime
    exp: datetime


def hash_token_jti(jti: str) -> str:
    """Return SHA-256 hex digest of a refresh token identifier."""
    return hashlib.sha256(jti.encode("utf-8")).hexdigest()


def hash_client_ip(ip_address: str | None, *, secret_key: str) -> str | None:
    """Return keyed HMAC-SHA256 digest so raw IPs are not stored in DB/audit records."""
    if not ip_address:
        return None
    return hmac.new(
        secret_key.encode("utf-8"),
        ip_address.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def create_access_token(
    *,
    user_id: uuid.UUID,
    settings: Settings,
    family_id: str | None = None,
    now: datetime | None = None,
) -> tuple[str, TokenClaims]:
    """Mint a short-lived signed JWT access token bound to a session family when issued by auth."""
    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + timedelta(minutes=settings.jwt_access_ttl_minutes)
    jti = uuid.uuid4().hex
    payload: dict[str, object] = {
        "sub": str(user_id),
        "typ": "access",
        "jti": jti,
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    if family_id is not None:
        payload["fam"] = family_id
    encoded = jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)
    return encoded, TokenClaims(
        sub=user_id,
        typ="access",
        jti=jti,
        fam=family_id,
        iat=issued_at,
        exp=expires_at,
    )


def create_refresh_token(
    *,
    user_id: uuid.UUID,
    family_id: str,
    settings: Settings,
    now: datetime | None = None,
) -> tuple[str, TokenClaims]:
    """Mint a rotating signed JWT refresh token bound to a token family."""
    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + timedelta(days=settings.jwt_refresh_ttl_days)
    jti = uuid.uuid4().hex
    payload = {
        "sub": str(user_id),
        "typ": "refresh",
        "fam": family_id,
        "jti": jti,
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    encoded = jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)
    return encoded, TokenClaims(
        sub=user_id,
        typ="refresh",
        jti=jti,
        fam=family_id,
        iat=issued_at,
        exp=expires_at,
    )


def decode_token(
    token: str,
    *,
    settings: Settings,
    expected_typ: Literal["access", "refresh"],
) -> TokenClaims:
    """Strictly verify JWT signature, issuer, audience, expiry, and token type."""
    try:
        raw = cast(
            dict[str, object],
            jwt.decode(
                token,
                settings.secret_key,
                algorithms=[JWT_ALGORITHM],
                issuer=JWT_ISSUER,
                audience=JWT_AUDIENCE,
                options={"require": ["sub", "typ", "jti", "iss", "aud", "iat", "exp"]},
            ),
        )
    except jwt.ExpiredSignatureError as exc:
        raise ChairAPIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="TOKEN_EXPIRED",
            message="Authentication token has expired.",
        ) from exc
    except jwt.PyJWTError as exc:
        raise ChairAPIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_TOKEN",
            message="Authentication token is invalid.",
        ) from exc

    typ = raw.get("typ")
    if typ != expected_typ:
        raise ChairAPIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_TOKEN_TYPE",
            message="Authentication token type mismatch.",
        )

    fam_raw = raw.get("fam")
    fam = str(fam_raw) if fam_raw is not None else None
    if expected_typ == "refresh" and not fam:
        raise ChairAPIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_TOKEN",
            message="Refresh token is missing session family.",
        )

    try:
        sub = uuid.UUID(str(raw["sub"]))
        iat = datetime.fromtimestamp(int(str(raw["iat"])), tz=UTC)
        exp = datetime.fromtimestamp(int(str(raw["exp"])), tz=UTC)
    except (TypeError, ValueError) as exc:
        raise ChairAPIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_TOKEN",
            message="Authentication token claims are malformed.",
        ) from exc

    return TokenClaims(
        sub=sub,
        typ=expected_typ,
        jti=str(raw["jti"]),
        fam=fam,
        iat=iat,
        exp=exp,
    )

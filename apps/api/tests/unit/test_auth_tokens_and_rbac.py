"""Unit tests for JWT tokens, atomic OTP/refresh state store, and RBAC tenant scope."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from chair_api.core.auth_store import (
    InMemoryAuthStore,
    OTPChallengeRecord,
    RefreshFamilyRecord,
)
from chair_api.core.config import Settings
from chair_api.core.errors import ChairAPIError
from chair_api.db.models.identity import User
from chair_api.domain.enums import UserRole
from chair_api.security.rbac import AuthPrincipal, RoleScope
from chair_api.security.tokens import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_token_jti,
)


def test_access_and_refresh_tokens_enforce_claims_and_reject_tampering() -> None:
    settings = Settings(app_env="test", secret_key="test-signing-key-32-bytes-minimum")
    user_id = uuid.uuid4()
    now = datetime.now(UTC)

    access_jwt, access_claims = create_access_token(
        user_id=user_id, settings=settings, family_id="fam-123", now=now
    )
    refresh_jwt, refresh_claims = create_refresh_token(
        user_id=user_id, family_id="fam-123", settings=settings, now=now
    )

    decoded_access = decode_token(access_jwt, settings=settings, expected_typ="access")
    assert decoded_access.sub == user_id
    assert decoded_access.jti == access_claims.jti
    assert decoded_access.fam == "fam-123"

    decoded_refresh = decode_token(refresh_jwt, settings=settings, expected_typ="refresh")
    assert decoded_refresh.sub == user_id
    assert decoded_refresh.fam == "fam-123"
    assert decoded_refresh.jti == refresh_claims.jti

    # Token type confusion must fail
    with pytest.raises(ChairAPIError) as exc_wrong_typ:
        decode_token(refresh_jwt, settings=settings, expected_typ="access")
    assert exc_wrong_typ.value.status_code == 401

    # Algorithm none / signature stripping must fail
    unsigned_jwt = jwt.encode(
        {
            "sub": str(user_id),
            "typ": "access",
            "iss": "chair-api",
            "aud": "chair-clients",
            "jti": "fake",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=10)).timestamp()),
        },
        key=None,
        algorithm="none",
    )
    with pytest.raises(ChairAPIError) as exc_alg_none:
        decode_token(unsigned_jwt, settings=settings, expected_typ="access")
    assert exc_alg_none.value.status_code == 401

    # Expired token must fail
    expired_jwt, _ = create_access_token(
        user_id=user_id,
        settings=settings,
        now=now - timedelta(hours=2),
    )
    with pytest.raises(ChairAPIError) as exc_expired:
        decode_token(expired_jwt, settings=settings, expected_typ="access")
    assert exc_expired.value.status_code == 401


async def test_in_memory_auth_store_rate_limits_single_active_challenge_and_locks() -> None:
    store = InMemoryAuthStore()
    phone = "+919876543210"
    ip_key = "ip-hash-1"

    # IP limit checked before incrementing phone bucket
    for _ in range(2):
        assert (
            await store.check_and_increment_otp_rate_limit(
                phone_e164=phone,
                ip_key=ip_key,
                window_seconds=900,
                max_per_phone=3,
                max_per_ip=2,
            )
            is None
        )
    assert (
        await store.check_and_increment_otp_rate_limit(
            phone_e164=phone,
            ip_key=ip_key,
            window_seconds=900,
            max_per_phone=3,
            max_per_ip=2,
        )
        is not None
    )

    # New challenge invalidates prior challenge for same phone
    await store.save_otp_challenge(
        OTPChallengeRecord(
            challenge_id="chal-1",
            phone_e164=phone,
            provider="mock",
            attempts=0,
            created_at_iso=datetime.now(UTC).isoformat(),
        ),
        ttl_seconds=300,
    )
    await store.save_otp_challenge(
        OTPChallengeRecord(
            challenge_id="chal-2",
            phone_e164=phone,
            provider="mock",
            attempts=0,
            created_at_iso=datetime.now(UTC).isoformat(),
        ),
        ttl_seconds=300,
    )
    old_claim, _ = await store.claim_otp_attempt(
        challenge_id="chal-1", expected_phone=phone, max_attempts=3
    )
    assert old_claim == "missing"

    assert await store.claim_otp_attempt(
        challenge_id="chal-2", expected_phone=phone, max_attempts=2
    ) == ("claimed", 1)
    assert await store.claim_otp_attempt(
        challenge_id="chal-2", expected_phone=phone, max_attempts=2
    ) == ("claimed", 2)
    assert await store.claim_otp_attempt(
        challenge_id="chal-2", expected_phone=phone, max_attempts=2
    ) == ("locked", 2)


async def test_refresh_family_atomic_cas_rotation_and_revocation() -> None:
    store = InMemoryAuthStore()
    user_id = str(uuid.uuid4())
    jti1 = hash_token_jti("jti-1")
    jti2 = hash_token_jti("jti-2")
    jti3 = hash_token_jti("jti-3")

    await store.save_refresh_family(
        RefreshFamilyRecord(
            family_id="fam-abc",
            user_id=user_id,
            active_jti_hash=jti1,
            revoked=False,
        ),
        ttl_seconds=86400,
    )

    assert (
        await store.rotate_refresh_family(
            family_id="fam-abc",
            expected_user_id=user_id,
            expected_jti_hash=jti1,
            new_jti_hash=jti2,
            ttl_seconds=86400,
        )
        == "rotated"
    )
    # Replaying jti1 marks family revoked
    assert (
        await store.rotate_refresh_family(
            family_id="fam-abc",
            expected_user_id=user_id,
            expected_jti_hash=jti1,
            new_jti_hash=jti3,
            ttl_seconds=86400,
        )
        == "reused"
    )
    assert (
        await store.rotate_refresh_family(
            family_id="fam-abc",
            expected_user_id=user_id,
            expected_jti_hash=jti2,
            new_jti_hash=jti3,
            ttl_seconds=86400,
        )
        == "revoked"
    )


def test_principal_rbac_and_tenant_scope_rules() -> None:
    salon_a = uuid.uuid4()
    branch_a1 = uuid.uuid4()
    branch_a2 = uuid.uuid4()
    salon_b = uuid.uuid4()
    branch_b1 = uuid.uuid4()

    customer_user = User(id=uuid.uuid4(), phone_e164="+919000000010", preferred_locale="en")
    customer = AuthPrincipal(
        user=customer_user,
        roles=(RoleScope(id=uuid.uuid4(), role=UserRole.CUSTOMER, salon_id=None, branch_id=None),),
        role_set=frozenset({UserRole.CUSTOMER}),
        request_id="req-1",
        ip_address="127.0.0.1",
        ip_hash="hash-1",
        user_agent="pytest",
    )
    assert customer.can_access_salon(salon_a) is False
    assert customer.can_access_branch(branch_a1, salon_a) is False

    owner_user = User(id=uuid.uuid4(), phone_e164="+919000000011", preferred_locale="en")
    owner = AuthPrincipal(
        user=owner_user,
        roles=(
            RoleScope(
                id=uuid.uuid4(),
                role=UserRole.PARTNER_OWNER,
                salon_id=salon_a,
                branch_id=None,
            ),
        ),
        role_set=frozenset({UserRole.PARTNER_OWNER}),
        request_id="req-2",
        ip_address="127.0.0.1",
        ip_hash="hash-2",
        user_agent="pytest",
    )
    assert owner.can_access_salon(salon_a) is True
    assert owner.can_access_salon(salon_b) is False
    assert owner.can_access_branch(branch_a1, salon_a) is True
    assert owner.can_access_branch(branch_a2, salon_a) is True
    assert owner.can_access_branch(branch_b1, salon_b) is False

    branch_staff_user = User(id=uuid.uuid4(), phone_e164="+919000000012", preferred_locale="en")
    branch_staff = AuthPrincipal(
        user=branch_staff_user,
        roles=(
            RoleScope(
                id=uuid.uuid4(),
                role=UserRole.PARTNER_STAFF,
                salon_id=salon_a,
                branch_id=branch_a1,
            ),
        ),
        role_set=frozenset({UserRole.PARTNER_STAFF}),
        request_id="req-3",
        ip_address="127.0.0.1",
        ip_hash="hash-3",
        user_agent="pytest",
    )
    assert branch_staff.can_access_branch(branch_a1, salon_a) is True
    assert branch_staff.can_access_branch(branch_a2, salon_a) is False
    # Branch-scoped staff MUST NOT pass salon-level access checks
    assert branch_staff.can_access_salon(salon_a) is False
    assert branch_staff.can_access_salon(salon_a, allowed_roles=(UserRole.PARTNER_OWNER,)) is False

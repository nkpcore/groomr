"""Live Postgres + Redis integration tests for atomic OTP, refresh rotation, RBAC, & DPDP."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from chair_api.core.config import Settings
from chair_api.db.models import AuditLog, Branch, Salon, User, UserConsent, UserRoleAssignment
from chair_api.main import create_app
from chair_api.security.tokens import create_access_token


@pytest.fixture
async def live_auth_client(
    postgres_test_engine: AsyncEngine,
) -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession], Settings]]:
    """Create FastAPI AsyncClient backed by test Postgres + isolated Redis DB 15."""
    test_redis_url = "redis://localhost:6379/15"
    redis_probe = Redis.from_url(test_redis_url, decode_responses=True, socket_connect_timeout=1.0)
    try:
        await redis_probe.ping()
        await redis_probe.flushdb()
    except Exception as exc:
        await redis_probe.aclose()
        pytest.skip(f"Redis unavailable for integration test ({type(exc).__name__}).")
    await redis_probe.aclose()

    db_url = postgres_test_engine.url.render_as_string(hide_password=False)
    settings = Settings(
        app_env="test",
        secret_key="integration-test-secret-key-at-least-32-bytes",
        database_url=db_url,
        test_database_url=db_url,
        redis_url=test_redis_url,
        auth_otp_provider="mock",
        otp_request_max_per_phone=5,
        otp_verify_max_attempts=3,
        otp_verify_max_failures_per_window=4,
    )
    app = create_app(settings)
    session_factory = async_sessionmaker(
        postgres_test_engine, expire_on_commit=False, class_=AsyncSession
    )

    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            yield client, session_factory, settings


async def _login_via_mock_otp(client: AsyncClient, phone_e164: str) -> dict[str, object]:
    req_res = await client.post("/api/v1/auth/otp/request", json={"phone_e164": phone_e164})
    assert req_res.status_code == 200, req_res.text
    challenge_id = req_res.json()["challenge_id"]

    ver_res = await client.post(
        "/api/v1/auth/otp/verify",
        json={"challenge_id": challenge_id, "phone_e164": phone_e164, "otp_code": "123456"},
    )
    assert ver_res.status_code == 200, ver_res.text
    return dict(ver_res.json())


async def test_otp_login_profile_consents_refresh_reuse_expired_logout_and_audit_privacy(
    live_auth_client: tuple[AsyncClient, async_sessionmaker[AsyncSession], Settings],
) -> None:
    client, session_factory, settings = live_auth_client
    phone = f"+9196{uuid.uuid4().int % 10**8:08d}"

    try:
        # 1. Request challenge twice -> earlier challenge must be invalidated immediately
        req1 = await client.post("/api/v1/auth/otp/request", json={"phone_e164": phone})
        req2 = await client.post("/api/v1/auth/otp/request", json={"phone_e164": phone})
        assert req1.status_code == 200 and req2.status_code == 200
        old_ver = await client.post(
            "/api/v1/auth/otp/verify",
            json={
                "challenge_id": req1.json()["challenge_id"],
                "phone_e164": phone,
                "otp_code": "123456",
            },
        )
        assert old_ver.status_code == 401

        # 2. Verify active challenge with excessive X-Request-ID (>64 chars must not 500)
        ver_res = await client.post(
            "/api/v1/auth/otp/verify",
            headers={"X-Request-ID": "x" * 120 + "\r\n"},
            json={
                "challenge_id": req2.json()["challenge_id"],
                "phone_e164": phone,
                "otp_code": "123456",
            },
        )
        assert ver_res.status_code == 200
        assert len(ver_res.headers["X-Request-ID"]) <= 64
        login_data = dict(ver_res.json())

        access_token = str(login_data["access_token"])
        refresh_1 = str(login_data["refresh_token"])
        headers = {"Authorization": f"Bearer {access_token}"}

        # 3. Fetch profile & update PII + locale (normalized lowercase email)
        me_res = await client.get("/api/v1/users/me", headers=headers)
        assert me_res.status_code == 200
        me = me_res.json()
        assert me["phone_e164"] == phone
        assert [r["role"] for r in me["roles"]] == ["CUSTOMER"]

        patch_res = await client.patch(
            "/api/v1/users/me",
            headers=headers,
            json={
                "full_name": "[DEMO] Integration User",
                "email": "USER.Demo@Example.COM",
                "preferred_locale": "hi",
            },
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["email"] == "user.demo@example.com"
        assert patch_res.json()["preferred_locale"] == "hi"

        # 4. Grant and revoke DPDP consents (invalid policy version rejected cleanly)
        bad_ver = await client.put(
            "/api/v1/users/me/consents",
            headers=headers,
            json={"decisions": [{"consent_type": "TERMS", "granted": True, "version": "bad-v"}]},
        )
        assert bad_ver.status_code == 422

        consent_res = await client.put(
            "/api/v1/users/me/consents",
            headers=headers,
            json={
                "decisions": [
                    {"consent_type": "TERMS", "granted": True, "version": "v1.0"},
                    {"consent_type": "PRIVACY_DPDP", "granted": True, "version": "v1.0"},
                    {"consent_type": "MARKETING", "granted": False, "version": "v1.0"},
                    {"consent_type": "STYLE_PASSPORT_PHOTOS", "granted": True, "version": "v1.0"},
                ]
            },
        )
        assert consent_res.status_code == 200
        history_len_before = len(consent_res.json()["history"])

        # Saving identical consents does not spam duplicate UserConsent rows
        noop_res = await client.put(
            "/api/v1/users/me/consents",
            headers=headers,
            json={
                "decisions": [
                    {"consent_type": "TERMS", "granted": True, "version": "v1.0"},
                ]
            },
        )
        assert noop_res.status_code == 200
        assert len(noop_res.json()["history"]) == history_len_before

        revoke_res = await client.put(
            "/api/v1/users/me/consents",
            headers=headers,
            json={
                "decisions": [
                    {"consent_type": "STYLE_PASSPORT_PHOTOS", "granted": False, "version": "v1.0"}
                ]
            },
        )
        assert revoke_res.status_code == 200
        revoked_map = {c["consent_type"]: c for c in revoke_res.json()["consents"]}
        assert revoked_map["STYLE_PASSPORT_PHOTOS"]["granted"] is False
        assert revoked_map["STYLE_PASSPORT_PHOTOS"]["revoked_at"] is not None

        # Verify audit_logs never expose raw IP or plaintext name/email PII
        async with session_factory() as s:
            user_id = uuid.UUID(me["id"])
            audit_rows = list(
                await s.scalars(select(AuditLog).where(AuditLog.actor_user_id == user_id))
            )
            audit_actions = [row.action for row in audit_rows]
            assert "USER_LOGIN" in audit_actions
            assert "USER_PROFILE_UPDATED" in audit_actions
            assert "USER_CONSENT_UPDATED" in audit_actions
            for row in audit_rows:
                assert row.ip_address is None or len(row.ip_address) == 64
                if row.action == "USER_PROFILE_UPDATED":
                    serialized = str(row.after_state_json)
                    assert "[DEMO] Integration User" not in serialized
                    assert "user.demo@example.com" not in serialized

        # 5. Concurrent refresh race -> at most one succeeds, replay revokes family
        r_a, r_b = await asyncio.gather(
            client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_1}),
            client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_1}),
        )
        statuses = sorted([r_a.status_code, r_b.status_code])
        assert statuses == [200, 401]
        winner_json = r_a.json() if r_a.status_code == 200 else r_b.json()
        refresh_2 = str(winner_json["refresh_token"])

        # Any further replay fails because family was revoked by concurrent collision
        after_reuse = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_2})
        assert after_reuse.status_code == 401

        # Old access token from revoked family is immediately rejected
        revoked_me = await client.get("/api/v1/users/me", headers=headers)
        assert revoked_me.status_code == 401
        assert revoked_me.json()["error"]["code"] == "SESSION_REVOKED"

        # 6. Fresh login + logout WITH AN EXPIRED access token still revokes refresh + access
        login_2 = await _login_via_mock_otp(client, phone)
        expired_access, _ = create_access_token(
            user_id=uuid.UUID(str(login_2["user_id"])),
            settings=settings,
            now=datetime.now(UTC) - timedelta(hours=2),
        )
        logout_res = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {expired_access}"},
            json={"refresh_token": login_2["refresh_token"]},
        )
        assert logout_res.status_code == 200
        post_logout_refresh = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": login_2["refresh_token"]}
        )
        assert post_logout_refresh.status_code == 401

        post_logout_me = await client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {login_2['access_token']}"},
        )
        assert post_logout_me.status_code == 401
    finally:
        async with session_factory() as s:
            user = await s.scalar(select(User).where(User.phone_e164 == phone))
            if user is not None:
                await s.execute(delete(AuditLog).where(AuditLog.actor_user_id == user.id))
                await s.execute(delete(UserConsent).where(UserConsent.user_id == user.id))
                await s.execute(
                    delete(UserRoleAssignment).where(UserRoleAssignment.user_id == user.id)
                )
                await s.delete(user)
                await s.commit()


async def test_parallel_otp_verify_single_use_and_rate_limits(
    live_auth_client: tuple[AsyncClient, async_sessionmaker[AsyncSession], Settings],
) -> None:
    client, session_factory, _ = live_auth_client
    phone = f"+9195{uuid.uuid4().int % 10**8:08d}"

    try:
        # Parallel verify with valid OTP on one challenge -> only 1 coroutine may succeed
        req_ok = await client.post("/api/v1/auth/otp/request", json={"phone_e164": phone})
        assert req_ok.status_code == 200
        chal_id = req_ok.json()["challenge_id"]

        v1, v2, v3 = await asyncio.gather(
            client.post(
                "/api/v1/auth/otp/verify",
                json={"challenge_id": chal_id, "phone_e164": phone, "otp_code": "123456"},
            ),
            client.post(
                "/api/v1/auth/otp/verify",
                json={"challenge_id": chal_id, "phone_e164": phone, "otp_code": "123456"},
            ),
            client.post(
                "/api/v1/auth/otp/verify",
                json={"challenge_id": chal_id, "phone_e164": phone, "otp_code": "123456"},
            ),
        )
        assert sorted([v1.status_code, v2.status_code, v3.status_code]) == [200, 401, 401]

        # Attempt lockout and cross-challenge phone cooldown
        req_bad = await client.post("/api/v1/auth/otp/request", json={"phone_e164": phone})
        assert req_bad.status_code == 200
        bad_chal = req_bad.json()["challenge_id"]
        for expected_status in (401, 401, 429):
            res = await client.post(
                "/api/v1/auth/otp/verify",
                json={"challenge_id": bad_chal, "phone_e164": phone, "otp_code": "000000"},
            )
            assert res.status_code == expected_status

        # Per-phone request rate limit (remaining out of 5 -> 3 left before 429)
        for _ in range(3):
            ok = await client.post("/api/v1/auth/otp/request", json={"phone_e164": phone})
            assert ok.status_code == 200
        limited = await client.post("/api/v1/auth/otp/request", json={"phone_e164": phone})
        assert limited.status_code == 429
        assert limited.json()["error"]["code"] == "OTP_RATE_LIMITED"
    finally:
        async with session_factory() as s:
            user = await s.scalar(select(User).where(User.phone_e164 == phone))
            if user is not None:
                await s.execute(delete(AuditLog).where(AuditLog.actor_user_id == user.id))
                await s.execute(
                    delete(UserRoleAssignment).where(UserRoleAssignment.user_id == user.id)
                )
                await s.delete(user)
                await s.commit()


async def test_rbac_and_tenant_branch_idor_isolation(
    live_auth_client: tuple[AsyncClient, async_sessionmaker[AsyncSession], Settings],
) -> None:
    client, session_factory, _ = live_auth_client
    owner_a_phone = f"+9194{uuid.uuid4().int % 10**8:08d}"
    owner_b_phone = f"+9193{uuid.uuid4().int % 10**8:08d}"
    customer_phone = f"+9192{uuid.uuid4().int % 10**8:08d}"
    admin_phone = f"+9191{uuid.uuid4().int % 10**8:08d}"

    created_user_ids: list[uuid.UUID] = []
    created_salon_ids: list[uuid.UUID] = []
    created_branch_ids: list[uuid.UUID] = []

    try:
        async with session_factory() as s:
            owner_a = User(phone_e164=owner_a_phone, full_name="[DEMO] Owner A")
            owner_b = User(phone_e164=owner_b_phone, full_name="[DEMO] Owner B")
            customer = User(phone_e164=customer_phone, full_name="[DEMO] Customer")
            admin = User(phone_e164=admin_phone, full_name="[DEMO] Admin")
            s.add_all([owner_a, owner_b, customer, admin])
            await s.flush()
            created_user_ids.extend([owner_a.id, owner_b.id, customer.id, admin.id])

            salon_a = Salon(
                owner_user_id=owner_a.id,
                legal_name="[DEMO] Salon A Pvt Ltd",
                brand_name="[DEMO] Salon A",
                status="ACTIVE",
            )
            salon_b = Salon(
                owner_user_id=owner_b.id,
                legal_name="[DEMO] Salon B Pvt Ltd",
                brand_name="[DEMO] Salon B",
                status="ACTIVE",
            )
            s.add_all([salon_a, salon_b])
            await s.flush()
            created_salon_ids.extend([salon_a.id, salon_b.id])

            branch_a = Branch(
                salon_id=salon_a.id,
                name="[DEMO] Branch A1",
                slug=f"demo-a1-{uuid.uuid4().hex[:8]}",
                address_line1="100 Feet Rd",
                city="Bengaluru",
                state="Karnataka",
                pincode="560038",
                location="SRID=4326;POINT(77.6408 12.9784)",
                operating_hours_json={},
            )
            branch_b = Branch(
                salon_id=salon_b.id,
                name="[DEMO] Branch B1",
                slug=f"demo-b1-{uuid.uuid4().hex[:8]}",
                address_line1="Pali Hill",
                city="Mumbai",
                state="Maharashtra",
                pincode="400050",
                location="SRID=4326;POINT(72.8295 19.0607)",
                operating_hours_json={},
            )
            s.add_all([branch_a, branch_b])
            await s.flush()
            created_branch_ids.extend([branch_a.id, branch_b.id])

            s.add_all(
                [
                    UserRoleAssignment(
                        user_id=owner_a.id, role="PARTNER_OWNER", salon_id=salon_a.id
                    ),
                    UserRoleAssignment(
                        user_id=owner_b.id, role="PARTNER_OWNER", salon_id=salon_b.id
                    ),
                    UserRoleAssignment(user_id=customer.id, role="CUSTOMER"),
                    UserRoleAssignment(user_id=admin.id, role="ADMIN"),
                ]
            )
            await s.commit()

        owner_a_tokens = await _login_via_mock_otp(client, owner_a_phone)
        customer_tokens = await _login_via_mock_otp(client, customer_phone)
        admin_tokens = await _login_via_mock_otp(client, admin_phone)

        owner_a_headers = {"Authorization": f"Bearer {owner_a_tokens['access_token']}"}
        customer_headers = {"Authorization": f"Bearer {customer_tokens['access_token']}"}
        admin_headers = {"Authorization": f"Bearer {admin_tokens['access_token']}"}

        # Customer blocked from Partner and Admin endpoints
        partner_denied = await client.get("/api/v1/partner/context", headers=customer_headers)
        admin_denied = await client.get("/api/v1/admin/audit-logs", headers=customer_headers)
        assert partner_denied.status_code == 403
        assert admin_denied.status_code == 403

        # Partner A sees only Salon A / Branch A, can access Branch A, gets 403 IDOR on Branch B
        ctx_res = await client.get("/api/v1/partner/context", headers=owner_a_headers)
        assert ctx_res.status_code == 200
        returned_branch_ids = [b["id"] for b in ctx_res.json()["branches"]]
        assert str(branch_a.id) in returned_branch_ids
        assert str(branch_b.id) not in returned_branch_ids

        own_branch = await client.get(
            f"/api/v1/partner/branches/{branch_a.id}/access",
            headers=owner_a_headers,
        )
        assert own_branch.status_code == 200
        assert own_branch.json()["branch_id"] == str(branch_a.id)

        other_branch = await client.get(
            f"/api/v1/partner/branches/{branch_b.id}/access",
            headers=owner_a_headers,
        )
        assert other_branch.status_code == 403

        # Partner A blocked from Admin endpoint; Admin succeeds
        partner_admin_denied = await client.get("/api/v1/admin/audit-logs", headers=owner_a_headers)
        assert partner_admin_denied.status_code == 403
        admin_logs = await client.get("/api/v1/admin/audit-logs", headers=admin_headers)
        assert admin_logs.status_code == 200
        assert len(admin_logs.json()["items"]) >= 1
    finally:
        async with session_factory() as s:
            for uid in created_user_ids:
                await s.execute(delete(AuditLog).where(AuditLog.actor_user_id == uid))
                await s.execute(delete(UserConsent).where(UserConsent.user_id == uid))
                await s.execute(
                    delete(UserRoleAssignment).where(UserRoleAssignment.user_id == uid)
                )
            for bid in created_branch_ids:
                await s.execute(delete(Branch).where(Branch.id == bid))
            for sid in created_salon_ids:
                await s.execute(delete(Salon).where(Salon.id == sid))
            for uid in created_user_ids:
                await s.execute(delete(User).where(User.id == uid))
            await s.commit()
